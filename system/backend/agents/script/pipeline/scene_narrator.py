"""Module 2: Scene Narrator — per-scene narration compiler.

Core rule: 1 scene -> 1 narration sentence.

LLM is REQUIRED. This module does NOT fall back to rule-based generation.
If the LLM provider is None or the LLM call fails, a RuntimeError is raised
so the caller knows narration quality cannot be guaranteed.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from backend.agents.script.prompts import NARRATOR_PROMPT_PATH, load_prompt
from backend.agents.script.speaking_rate import word_budget as speaking_word_budget
from backend.agents.script.utils import SCRIPT_LLM_BATCH_SIZE, SCRIPT_LLM_MAX_TOKENS, safe_extract_json
from backend.agents.script.pipeline.marketing_enricher import (
    sanitize_unverified_room_ranks,
    strip_instance_numbers,
)
from backend.schemas.script_schema import NarrativeStructure, StyleConfig
from backend.schemas.vision_schema import VisionKnowledgeBase
from backend.workflows.room_naming import narration_label
from backend.services.llm.base import LLMMessage, LLMProvider

logger = logging.getLogger(__name__)


class SceneNarrator:
    """Generates one narration sentence per scene (LLM primary, rule fallback)."""

    def __init__(self, llm_provider: LLMProvider | None = None) -> None:
        self.llm_provider = llm_provider

    async def narrate(
        self,
        vkb: VisionKnowledgeBase,
        planning: dict[str, Any],
        structure: NarrativeStructure,
        style: StyleConfig,
        words_per_minute: float = 150.0,
        coverage_plans: dict[str, Any] | None = None,
    ) -> dict[str, str]:
        """Produce a draft narration sentence for every scene, in video order.

        Raises RuntimeError if LLM is unavailable — no rule-based fallback.
        """
        if self.llm_provider is None:
            raise RuntimeError(
                "LLM provider is required for Scene Narrator. "
                "No rule-based fallback is available. "
                "Please ensure the LLM server is reachable before running the Script Agent."
            )

        segments = sorted(vkb.segments, key=lambda s: s.raw.start_time)
        role_by_id = self._role_by_id(planning)
        arc_by_id = dict(zip(structure.scene_order, structure.story_arc))
        narrative_by_id = {
            str(n.get("segment_id", "")): n for n in planning.get("narrative_flow", [])
        }
        timeline_by_id = {
            str(t.get("segment_id", "")): t for t in planning.get("timeline_plan", [])
        }
        emphasis_targets = [str(t) for t in (planning.get("emphasis_targets") or [])]

        llm_texts = await self._llm_narrate(
            segments, role_by_id, arc_by_id, narrative_by_id, timeline_by_id,
            style, words_per_minute, emphasis_targets,
            coverage_plans=coverage_plans,
        )

        missing = [seg.segment_id for seg in segments if not llm_texts.get(seg.segment_id, "").strip()]
        if missing:
            raise RuntimeError(
                f"LLM narration incomplete: {len(missing)}/{len(segments)} segments have no text "
                f"({', '.join(missing[:5])}{'...' if len(missing) > 5 else ''}). "
                "Check LLM response and retry."
            )

        logger.info("Scene Narrator produced %d LLM sentences", len(llm_texts))
        return {seg.segment_id: llm_texts[seg.segment_id] for seg in segments}

    async def renarrate_segments(
        self,
        vkb: VisionKnowledgeBase,
        planning: dict[str, Any],
        structure: NarrativeStructure,
        style: StyleConfig,
        segment_ids: list[str],
        coverage_plans: dict[str, Any],
        missing_by_segment: dict[str, list[str]],
        words_per_minute: float = 150.0,
    ) -> dict[str, str]:
        """Re-generate only coverage-failed segments with stronger must_mention hints."""
        wanted = set(segment_ids)
        segments = [s for s in sorted(vkb.segments, key=lambda s: s.raw.start_time) if s.segment_id in wanted]
        if not segments:
            return {}
        role_by_id = self._role_by_id(planning)
        arc_by_id = dict(zip(structure.scene_order, structure.story_arc))
        narrative_by_id = {
            str(n.get("segment_id", "")): n for n in planning.get("narrative_flow", [])
        }
        timeline_by_id = {
            str(t.get("segment_id", "")): t for t in planning.get("timeline_plan", [])
        }
        # Annotate plans with explicit missing list for the retry prompt
        retry_plans = dict(coverage_plans or {})
        for sid, missing in (missing_by_segment or {}).items():
            plan = retry_plans.get(sid)
            if plan is None:
                continue
            # pydantic model or dict
            if hasattr(plan, "model_copy"):
                retry_plans[sid] = plan.model_copy(
                    update={"must_mention": list(dict.fromkeys(list(plan.must_mention) + list(missing)))}
                )
            elif isinstance(plan, dict):
                plan = dict(plan)
                plan["must_mention"] = list(dict.fromkeys(list(plan.get("must_mention") or []) + list(missing)))
                retry_plans[sid] = plan

        return await self._llm_narrate(
            segments,
            role_by_id,
            arc_by_id,
            narrative_by_id,
            timeline_by_id,
            style,
            words_per_minute,
            [str(t) for t in (planning.get("emphasis_targets") or [])],
            coverage_plans=retry_plans,
            coverage_retry=True,
        )

    def _role_by_id(self, planning: dict[str, Any]) -> dict[str, str]:
        return {
            str(a.get("segment_id", "")): str(a.get("role", "SUPPORT")) or "SUPPORT"
            for a in planning.get("attention_map", [])
        }

    async def _llm_narrate(
        self,
        segments: list[Any],
        role_by_id: dict[str, str],
        arc_by_id: dict[str, str],
        narrative_by_id: dict[str, dict[str, Any]],
        timeline_by_id: dict[str, dict[str, Any]],
        style: StyleConfig,
        words_per_minute: float,
        emphasis_targets: list[str] | None = None,
        coverage_plans: dict[str, Any] | None = None,
        coverage_retry: bool = False,
    ) -> dict[str, str]:
        from backend.workflows.emphasis import matched_facts
        from backend.agents.script.pipeline.space_coverage import (
            SegmentCoveragePlan,
            plan_to_prompt_dict,
        )

        emphasis_targets = emphasis_targets or []
        coverage_plans = coverage_plans or {}
        payload = []
        for seg in segments:
            seg_id = seg.segment_id
            tl = timeline_by_id.get(seg_id, {})
            start = tl.get("start", seg.raw.start_time)
            end = tl.get("end", seg.raw.end_time)
            duration = max(end - start, 0.1)
            word_budget = speaking_word_budget(duration, style.language)
            narrative = narrative_by_id.get(seg_id, {})

            space_feature_bits: list[str] = []
            for space in seg.knowledge.spaces or []:
                # Glimpsed spaces (seen in passing through a doorway) must not
                # feed the narration — describing them here causes the
                # "talking about the bedroom while showing the kitchen" effect.
                role = getattr(space, "room_role", "")
                if role == "glimpse":
                    continue
                # Only the room we are standing in gets named. Handing the
                # narrator a secondary room's name is how a bedroom shot ends up
                # opening with "我们现在站在走廊里" — its features can still be
                # described, they are on camera; the label is what misleads.
                if role == "primary":
                    label = narration_label(space)
                    if label:
                        space_feature_bits.append(label)
                for feat in (space.features or [])[:2]:
                    if feat:
                        space_feature_bits.append(strip_instance_numbers(str(feat)))

            default_elements = (
                list(space_feature_bits)
                + [strip_instance_numbers(x) for x in seg.knowledge.selling_points[:4]]
                + [strip_instance_numbers(x) for x in seg.knowledge.furniture[:2]]
                + [strip_instance_numbers(x) for x in seg.knowledge.appliances[:2]]
            )
            emphasis_here = matched_facts(
                emphasis_targets, seg.knowledge.model_dump()
            ) if emphasis_targets else []
            emphasis_here = [strip_instance_numbers(x) for x in emphasis_here]
            visible_elements = list(
                dict.fromkeys(emphasis_here + default_elements)
            )[:8]

            plan_raw = coverage_plans.get(seg_id)
            if isinstance(plan_raw, SegmentCoveragePlan):
                coverage = plan_to_prompt_dict(plan_raw)
                narration_mode = plan_raw.narration_mode
                must_cover = list(plan_raw.must_mention)
            elif isinstance(plan_raw, dict):
                coverage = {
                    "main_space": plan_raw.get("main_space"),
                    "secondary_spaces": plan_raw.get("secondary_spaces") or [],
                    "must_mention": plan_raw.get("must_mention") or [],
                    "narration_mode": plan_raw.get("narration_mode") or "detail",
                    "narration_goal": plan_raw.get("narration_goal") or "",
                    "coverage_note": plan_raw.get("coverage_note")
                    or (
                        "Functional spaces still need a brief mention when required."
                    ),
                }
                narration_mode = str(coverage.get("narration_mode") or "detail")
                must_cover = list(coverage.get("must_mention") or [])
            else:
                coverage = {}
                narrative_fn_tmp = str(narrative.get("narrative_function", ""))
                narration_mode = (
                    "summary"
                    if "summarize private spaces" in narrative_fn_tmp.lower()
                    else "detail"
                )
                must_cover = []

            narrative_fn = str(narrative.get("narrative_function", ""))
            entry = {
                "segment_id": seg_id,
                "room_type": seg.knowledge.room_type,
                "coverage": coverage,
                "main_space": coverage.get("main_space"),
                "secondary_spaces": coverage.get("secondary_spaces") or [],
                "must_mention": must_cover,
                "must_cover_spaces": must_cover,
                "narration_mode": narration_mode,
                "visible_elements": visible_elements,
                "emphasis": emphasis_here,
                "lighting": seg.knowledge.lighting,
                "style": seg.knowledge.style,
                "role": role_by_id.get(seg_id, "SUPPORT"),
                "arc_stage": arc_by_id.get(seg_id, "explore"),
                "narrative_function": narrative_fn,
                "emotion": narrative.get("emotion", "neutral"),
                "duration_seconds": round(duration, 1),
                "word_budget": word_budget,
                "formula": "emotion + 1-3 concrete features + buyer benefit",
            }
            if coverage_retry:
                entry["coverage_retry"] = True
                entry["instruction"] = (
                    "Previous draft missed required spaces. "
                    "Rewrite ONE sentence that keeps the hero space and MUST include every "
                    f"name in must_mention={must_cover}. Combine naturally; do not list rooms."
                )
            payload.append(entry)

        results: dict[str, str] = {}
        batch_size = SCRIPT_LLM_BATCH_SIZE
        batches = [payload[i : i + batch_size] for i in range(0, len(payload), batch_size)]
        style_json = json.dumps(style.model_dump(), indent=2)

        for batch_idx, batch in enumerate(batches):
            logger.info(
                "Scene Narrator LLM batch %d/%d (%d scenes)%s",
                batch_idx + 1,
                len(batches),
                len(batch),
                " [coverage-retry]" if coverage_retry else "",
            )
            prompt = load_prompt(
                NARRATOR_PROMPT_PATH,
                style_json=style_json,
                scenes_json=json.dumps(batch, indent=2),
            )

            try:
                response = await self.llm_provider.generate(
                    messages=[LLMMessage(role="user", content=prompt)],
                    temperature=0.35 if coverage_retry else 0.4,
                    max_tokens=SCRIPT_LLM_MAX_TOKENS,
                )
            except Exception as exc:
                raise RuntimeError(
                    f"LLM call failed in Scene Narrator (batch {batch_idx + 1}/{len(batches)}): {exc}. "
                    "Ensure the LLM server is running and reachable."
                ) from exc

            if not response.content or not response.content.strip():
                raise RuntimeError(
                    f"LLM returned empty content for batch {batch_idx + 1}/{len(batches)} "
                    f"(finish_reason={response.finish_reason!r}). "
                    "The model may have exhausted its token budget. "
                    "Try reducing SCRIPT_LLM_BATCH_SIZE or switching to a non-reasoning model."
                )

            data = safe_extract_json(response.content, fallback=[])
            batch_result = self._parse_llm_narration(data)
            if not batch_result:
                raise RuntimeError(
                    f"LLM response for batch {batch_idx + 1}/{len(batches)} was unparseable. "
                    f"Raw response (first 400 chars): {response.content[:400]}"
                )

            results.update(batch_result)

        lang = (style.language or "zh").strip().lower()
        cleaned: dict[str, str] = {}
        prev_main = ""
        prev_end: float | None = None
        for seg in segments:
            sid = seg.segment_id
            text = results.get(sid, "")
            if not text:
                continue
            plan_raw = (coverage_plans or {}).get(sid)
            must: list[str] = []
            main = ""
            if isinstance(plan_raw, SegmentCoveragePlan):
                must = list(plan_raw.must_mention)
                if plan_raw.main_space:
                    main = plan_raw.main_space.narration_name
            elif isinstance(plan_raw, dict):
                must = list(plan_raw.get("must_mention") or [])
                ms = plan_raw.get("main_space") or {}
                if isinstance(ms, dict):
                    main = str(ms.get("type") or ms.get("narration_name") or "")
            start = float(getattr(seg.raw, "start_time", 0.0) or 0.0)
            adjacent_ok = (
                prev_end is not None
                and abs(start - float(prev_end)) <= 0.2
                and bool(prev_main)
            )
            cleaned[sid] = sanitize_unverified_room_ranks(
                text,
                must_mention=must,
                main_space=main,
                language=lang,
                previous_primary=prev_main,
                adjacent_ok=adjacent_ok,
            )
            prev_main = main
            prev_end = float(getattr(seg.raw, "end_time", 0.0) or 0.0)
        for sid, text in results.items():
            if sid not in cleaned:
                cleaned[sid] = sanitize_unverified_room_ranks(text, language=lang)
        return cleaned

    def _parse_llm_narration(self, data: Any) -> dict[str, str]:
        result: dict[str, str] = {}
        items = data
        if isinstance(data, dict):
            items = data.get("narration_segments", data.get("segments", []))
        if not isinstance(items, list):
            return result
        for item in items:
            if isinstance(item, dict) and item.get("segment_id") and item.get("text"):
                result[str(item["segment_id"])] = str(item["text"]).strip()
        return result

