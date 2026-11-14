"""Script Agent — Temporal Narration Compiler.

Answers: How should the property be described, in time-aligned,
voiceable narration?

Pipeline:
1. Narrative Planner   [Rule]              story_arc + scene_order
2. Scene Narrator      [LLM required]      1 scene -> 1 narration sentence
3. Style Controller    [Rule]              tone -> language constraints
4. Alignment Engine    [Rule]              fit narration to fixed scene timing
5. Validators          [Rule]              schema + timeline consistency

Additional capability:
  rewrite_for_timeline()  [Rule]  mechanically compress flagged segments
                                  so narration fits within video duration budget.
                                  Called by Timeline Agent's feedback loop.
                                  Does NOT invoke LLM.
"""

from __future__ import annotations

import logging
from typing import Any

import json

from backend.agents.script.pipeline.alignment_engine import AlignmentEngine
from backend.agents.script.pipeline.marketing_enricher import enrich_marketing_texts
from backend.agents.script.pipeline.narrative_planner import NarrativePlanner
from backend.agents.script.pipeline.scene_narrator import SceneNarrator
from backend.agents.script.pipeline.space_coverage import (
    build_coverage_plans,
    check_coverage,
)
from backend.agents.script.pipeline.style_controller import StyleController
from backend.agents.script.speaking_rate import (
    EN_WORDS_PER_MINUTE,
    estimated_duration as speak_estimated_duration,
)
from backend.agents.script.prompts import REWRITE_PROMPT_PATH, load_prompt
from backend.agents.script.utils import SCRIPT_LLM_MAX_TOKENS, clause_aware_trim, safe_extract_json
from backend.agents.script.validators.schema_validator import SchemaValidator
from backend.agents.script.validators.timeline_validator import TimelineValidator
from backend.core.base_agent import BaseAgent
from backend.schemas.script_schema import ScriptOutput, ScriptValidation
from backend.schemas.vision_schema import VisionKnowledgeBase
from backend.services.llm.base import LLMMessage
from backend.state.project_state import ProjectState

logger = logging.getLogger(__name__)

DEFAULT_WORDS_PER_MINUTE = EN_WORDS_PER_MINUTE
DEFAULT_MAX_SEGMENT_WORDS = 100
MAX_COVERAGE_RETRIES = 1
# Floor for timeline-driven compression. Below this a Chinese line loses its
# subject and reads as listing shorthand (「落地窗对景城市景观」), which is worse
# on camera than stretching the shot a little further. Slow-motion covers the
# remaining gap instead.
ZH_MIN_NARRATION_CHARS = 18
EN_MIN_NARRATION_WORDS = 6

_ZH_CLAUSE_BREAKS = "，、；：,;:"


def _zh_clause_trim(text: str, max_chars: int) -> str:
    """Trim Chinese narration at clause boundaries to fit a character budget.

    Keeps whole clauses (split on ，、；：) until the next clause would exceed
    the budget; always keeps at least the first clause and closes with 。
    """
    body = text.strip().rstrip("。！？.!?")
    if len(body) <= max_chars:
        return text
    clauses: list[str] = []
    current = ""
    for ch in body:
        current += ch
        if ch in _ZH_CLAUSE_BREAKS:
            clauses.append(current)
            current = ""
    if current:
        clauses.append(current)
    kept = clauses[0].rstrip(_ZH_CLAUSE_BREAKS)
    total = len(kept)
    for clause in clauses[1:]:
        clean = clause.rstrip(_ZH_CLAUSE_BREAKS)
        if total + 1 + len(clean) > max_chars:
            break
        kept += "，" + clean
        total = len(kept)
    return kept + "。"


class ScriptAgent(BaseAgent):
    """Temporal narration compiler: Vision + Planner -> time-aligned narration."""

    agent_name = "script"
    state_key = "script"

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        llm_provider: Any | None = None,
    ) -> None:
        super().__init__(config)
        self.llm_provider = llm_provider

        script_cfg = self.config.get("script", self.config)
        self.words_per_minute = float(script_cfg.get("words_per_minute", DEFAULT_WORDS_PER_MINUTE))
        self.max_segment_words = int(script_cfg.get("max_segment_words", DEFAULT_MAX_SEGMENT_WORDS))
        tolerance = float(script_cfg.get("alignment_tolerance", 0.25))

        self.narrative_planner = NarrativePlanner()
        self.scene_narrator = SceneNarrator(llm_provider)
        self.style_controller = StyleController()
        self.alignment_engine = AlignmentEngine(
            words_per_minute=self.words_per_minute,
            max_segment_words=self.max_segment_words,
            tolerance=tolerance,
        )
        self.schema_validator = SchemaValidator()
        self.timeline_validator = TimelineValidator()

    async def run(self, state: ProjectState) -> ProjectState:
        """Execute the temporal narration compilation pipeline."""
        vkb = self._load_vkb(state)
        planning = state.planning or {}
        if not planning:
            raise ValueError("Planning output is required but state.planning is empty")

        intent = planning.get("intent", {})
        meta = (state.user_goal.property_metadata if state.user_goal else None) or {}
        language = str(
            meta.get("narration_language")
            or intent.get("narration_language")
            or "en"
        ).lower()
        if language not in ("en", "zh"):
            language = "en"

        logger.info(
            "Compiling narration for %d scenes | tone=%s | language=%s",
            len(vkb.segments),
            intent.get("emotional_tone", ""),
            language,
        )

        # Module 3a: derive style constraints from Director Intent [Rule]
        style = self.style_controller.derive_style(intent, language=language)
        logger.info(
            "  style: tone=%s sentence_length=%s energy=%s language=%s",
            style.tone, style.sentence_length, style.energy, style.language,
        )

        # Module 1: Narrative Planner [Rule] — story arc labels
        structure = self.narrative_planner.plan(vkb, planning)
        logger.info("  arc: %s", list(zip(structure.scene_order, structure.story_arc))[:5])

        # Module 1b: Space Coverage Controller [Rule] — hero/support/required
        coverage_plans = build_coverage_plans(vkb, planning)
        logger.info(
            "  coverage: %d plans | required samples=%s",
            len(coverage_plans),
            {
                sid: p.must_mention
                for sid, p in list(coverage_plans.items())[-2:]
            },
        )

        # Module 2: Scene Narrator [LLM] — guided by coverage plan
        draft_texts = await self.scene_narrator.narrate(
            vkb,
            planning,
            structure,
            style,
            words_per_minute=self.words_per_minute,
            coverage_plans=coverage_plans,
        )

        # Module 2b: Coverage Checker — retry missing required spaces
        for attempt in range(MAX_COVERAGE_RETRIES):
            check = check_coverage(draft_texts, coverage_plans)
            if not check.coverage_failed:
                break
            logger.warning(
                "Coverage retry %d/%d for %s",
                attempt + 1,
                MAX_COVERAGE_RETRIES,
                check.missing_by_segment,
            )
            repaired = await self.scene_narrator.renarrate_segments(
                vkb,
                planning,
                structure,
                style,
                segment_ids=check.missing_segment_ids,
                coverage_plans=coverage_plans,
                missing_by_segment=check.missing_by_segment,
                words_per_minute=self.words_per_minute,
            )
            draft_texts.update(repaired)

        # Module 3b: Style Controller applies vocabulary constraints [Rule]
        styled_texts = {
            seg_id: self.style_controller.apply(text, style)
            for seg_id, text in draft_texts.items()
        }

        # Module 3c: Marketing enricher — fill weak mood-only / truncated lines
        # Also soft-patches any remaining Bathroom gaps as last resort.
        styled_texts = enrich_marketing_texts(styled_texts, vkb, language=language)

        final_check = check_coverage(styled_texts, coverage_plans)
        if final_check.coverage_failed:
            logger.warning(
                "Coverage still incomplete after enricher: %s",
                final_check.missing_by_segment,
            )

        # Module 4: Timeline Alignment Engine [Rule]
        narration_segments = self.alignment_engine.align(vkb, planning, structure, styled_texts, style)
        for seg in narration_segments[:3]:
            logger.info(
                "  %s [%s]: '%s' (%.1fs budget, status=%s)",
                seg.segment_id,
                seg.role,
                seg.text[:60],
                seg.scene_duration,
                seg.alignment_status,
            )

        # Validators [Rule]
        schema_issues = self.schema_validator.validate(narration_segments)
        timeline_issues = self.timeline_validator.validate(vkb, narration_segments, structure)
        coverage_issues = [
            f"{sid}: missing required spaces {names}"
            for sid, names in final_check.missing_by_segment.items()
        ]
        all_issues = schema_issues + timeline_issues + coverage_issues
        needs_rewrite = [s.segment_id for s in narration_segments if s.alignment_status == "needs_rewrite"]

        validation = ScriptValidation(
            is_valid=not all_issues,
            issues=all_issues,
            needs_rewrite_segments=needs_rewrite,
        )
        if all_issues:
            logger.warning("Script validation found %d issue(s): %s", len(all_issues), all_issues[:3])
        else:
            logger.info("Script validation passed")

        output = ScriptOutput(
            project_id=state.project_id,
            agent_name=self.agent_name,
            style=style,
            narrative_structure=structure,
            narration_segments=narration_segments,
            validation=validation,
            total_estimated_duration=round(sum(s.estimated_duration for s in narration_segments), 2),
        )
        data = output.model_dump()
        data["coverage_plans"] = {
            sid: plan.model_dump() for sid, plan in coverage_plans.items()
        }
        data["coverage_check"] = final_check.model_dump()
        return self.write_state(state, data)

    async def rewrite_for_timeline(
        self,
        state: ProjectState,
        rewrite_requests: list[dict],
    ) -> ProjectState:
        """Rewrite flagged narration segments to fit within video duration.

        Called by Timeline Agent's feedback loop for FLAG_REWRITE segments.

        Strategy:
          1. LLM rewrite (preferred) — intelligently rephrase to be concise
             while keeping the best selling point and natural cinematic tone.
          2. clause_aware_trim (fallback) — mechanical word-count compression
             used only when LLM is unavailable or the call fails.

        Each request must contain:
          source_ids:   list[str]   — original VKB segment IDs to rewrite
          video_duration: float     — total allocated video time in seconds
          audio_duration: float     — current narration audio duration (too long)
        """
        if not rewrite_requests:
            return state

        script_data = dict(state.script)
        style = script_data.get("style", {})
        narration_segs = {s["segment_id"]: dict(s) for s in script_data.get("narration_segments", [])}

        # Build flat list of per-segment rewrite tasks
        is_zh = (style.get("language") or "en").lower() == "zh"
        tasks: list[dict] = []
        compression_map: dict[str, float] = {}
        for req in rewrite_requests:
            video_dur = float(req.get("video_duration", 0))
            target_dur = float(req.get("target_audio_duration") or video_dur)
            audio_dur = float(req.get("audio_duration", 0))
            if target_dur <= 0 or audio_dur <= target_dur:
                continue
            ratio = target_dur / audio_dur
            for sid in req.get("source_ids", []):
                seg = narration_segs.get(sid)
                if not seg:
                    continue
                if is_zh:
                    # Chinese has no spaces — budget in characters (~4.2/sec).
                    max_words = max(
                        ZH_MIN_NARRATION_CHARS, int(len(seg["text"]) * ratio)
                    )
                    budget_unit = "characters"
                else:
                    max_words = max(
                        EN_MIN_NARRATION_WORDS, int(len(seg["text"].split()) * ratio)
                    )
                    budget_unit = "words"
                tasks.append({
                    "segment_id": sid,
                    "original_text": seg["text"],
                    "max_words": max_words,
                    "budget_unit": budget_unit,
                    "role": seg.get("role", "SUPPORT"),
                    "room_type": seg.get("room_type", ""),
                    "video_duration_seconds": round(target_dur, 1),
                })
                compression_map[sid] = ratio

        if not tasks:
            return state

        # Attempt LLM rewrite
        llm_results: dict[str, str] = {}
        if self.llm_provider is not None:
            llm_results = await self._llm_rewrite(tasks, style)

        # Apply results (LLM where available, clause_aware_trim as fallback)
        rewrites_applied = 0
        for task in tasks:
            sid = task["segment_id"]
            seg = narration_segs[sid]
            max_words = task["max_words"]

            if llm_results.get(sid, "").strip():
                new_text = llm_results[sid].strip()
                method = "llm"
            elif is_zh:
                new_text = _zh_clause_trim(seg["text"], max_words)
                method = "trim_fallback"
            else:
                new_text = clause_aware_trim(seg["text"], max_words)
                method = "trim_fallback"

            # HARD budget enforcement — the LLM often refuses to go short
            # enough for 2-4s shots, which is exactly where sub-0.5× playback
            # comes from. Cut at clause boundaries until the budget fits.
            if is_zh and len(new_text) > max_words * 1.25:
                trimmed = _zh_clause_trim(new_text, max_words)
                if trimmed and trimmed != new_text:
                    new_text = trimmed
                    method += "+clause_trim"
            elif not is_zh and len(new_text.split()) > max_words * 1.25:
                new_text = clause_aware_trim(new_text, max_words)
                method += "+clause_trim"

            logger.info(
                "rewrite_for_timeline [%s]: %s  %dw → %dw  '%s'",
                method, sid,
                len(seg["text"].split()),
                len(new_text.split()),
                new_text[:70],
            )

            seg["text"] = new_text
            lang = "zh" if is_zh else "en"
            seg["word_count"] = (
                len(new_text.replace(" ", "")) if is_zh else len(new_text.split())
            )
            seg["estimated_duration"] = speak_estimated_duration(new_text, lang)
            seg["alignment_status"] = "rewritten_by_timeline"
            seg["alignment_notes"] = [*seg.get("alignment_notes", []), f"timeline_rewrite_{method}"]
            rewrites_applied += 1

        if rewrites_applied:
            script_data["narration_segments"] = list(narration_segs.values())
            script_data["total_estimated_duration"] = round(
                sum(s.get("estimated_duration", 0) for s in script_data["narration_segments"]), 2
            )
            logger.info(
                "rewrite_for_timeline: %d segments rewritten | new total_estimated=%.1fs",
                rewrites_applied, script_data["total_estimated_duration"],
            )
            state_dict = state.model_dump()
            state_dict["script"] = script_data
            return ProjectState(**state_dict)

        return state

    async def _llm_rewrite(self, tasks: list[dict], style: dict) -> dict[str, str]:
        """Call LLM to rewrite segments. Returns {segment_id: new_text} for successful ones."""
        prompt = load_prompt(
            REWRITE_PROMPT_PATH,
            style_json=json.dumps(style, indent=2),
            segments_json=json.dumps(tasks, indent=2),
        )
        try:
            response = await self.llm_provider.generate(
                messages=[LLMMessage(role="user", content=prompt)],
                temperature=0.3,
                max_tokens=SCRIPT_LLM_MAX_TOKENS,
            )
        except Exception as exc:
            logger.warning("LLM rewrite call failed (%s) — falling back to trim", exc)
            return {}

        if not response.content or not response.content.strip():
            logger.warning("LLM rewrite returned empty content — falling back to trim")
            return {}

        data = safe_extract_json(response.content, fallback=[])
        results: dict[str, str] = {}
        items = data if isinstance(data, list) else data.get("segments", []) if isinstance(data, dict) else []
        for item in items:
            if isinstance(item, dict) and item.get("segment_id") and item.get("text"):
                results[str(item["segment_id"])] = str(item["text"]).strip()

        logger.info("LLM rewrite: %d/%d segments succeeded", len(results), len(tasks))
        return results

    def _load_vkb(self, state: ProjectState) -> VisionKnowledgeBase:
        vision_data = state.vision or {}
        if not vision_data:
            raise ValueError("Vision Knowledge Base is required but state.vision is empty")
        from backend.agents.vision.modules.space_evidence_validator import validate_verified_vkb
        from backend.workflows.room_naming import normalize_room_names

        vkb = validate_verified_vkb(VisionKnowledgeBase(**vision_data))
        vkb = normalize_room_names(vkb)
        state.vision = vkb.model_dump()
        return vkb
