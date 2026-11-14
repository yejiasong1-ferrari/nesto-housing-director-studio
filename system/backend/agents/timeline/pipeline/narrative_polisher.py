"""Narrative Polisher — LLM coherence pass after Timeline unify.

Runs AFTER NarrationUnifier. Polishes the full timeline-aligned script for:
  - narrative coherence across segments
  - de-duplication of repeated phrases
  - visual alignment (text matches on-screen room / focus)

Does NOT change timings, merge segments, or invent features.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from backend.agents.script.speaking_rate import (
    speakable_window,
    word_budget as speaking_word_budget,
)
from backend.agents.script.pipeline.marketing_enricher import sanitize_timeline_narration

logger = logging.getLogger(__name__)

_PROMPT_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "prompts" / "timeline" / "narrative_polish.md"
)

AUDIO_TAIL_PAD = 0.35  # leave room so last syllable isn't clipped


def _load_prompt(**kwargs: str) -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8").format(**kwargs)


class NarrativePolisher:
    """LLM polish of timeline-aligned narration (cognitive, not media)."""

    def __init__(self, llm_provider: Any | None = None) -> None:
        self.llm_provider = llm_provider

    async def polish(
        self,
        unified_segments: list[dict[str, Any]],
        timeline: dict[str, Any],
        style: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        if not unified_segments:
            return unified_segments

        tl_by_safe = {
            str(s.get("id", "")).split("[", 1)[0]: s
            for s in timeline.get("segments", [])
        }
        is_zh = ((style or {}).get("language") or "en").lower() == "zh"

        payloads: list[dict] = []
        for ns in unified_segments:
            sid = str(ns.get("segment_id", ""))
            tl = tl_by_safe.get(sid, {})
            source = tl.get("source", {})
            visual = tl.get("visual_plan", {})
            window = float(
                ns.get("scene_duration")
                or tl.get("duration_decision", {}).get("editing_window")
                or source.get("video_duration")
                or 0
            )
            # Reserve pad so TTS fits comfortably inside the visual window, and
            # keep the budget tied to real footage so a short shot gets a short
            # line instead of being slowed down to cover a long one.
            speak_window = speakable_window(
                window,
                source.get("video_duration") or 0,
                pad=AUDIO_TAIL_PAD,
            )
            word_budget = speaking_word_budget(
                speak_window,
                "zh" if is_zh else "en",
                min_units=12 if is_zh else 6,
            )

            payloads.append({
                "segment_id": sid,
                "text": ns.get("text", ""),
                "room_type": ns.get("room_type") or tl.get("room_type", ""),
                "role": ns.get("role") or tl.get("role", "SUPPORT"),
                "arc_stage": ns.get("arc_stage") or tl.get("arc_stage", ""),
                "story_phase": ns.get("story_phase") or visual.get("story_phase", ""),
                "focus_elements": visual.get("focus_elements", [])[:5],
                "video_start": source.get("video_start", ns.get("start_time", 0)),
                "video_end": source.get("video_end", ns.get("end_time", 0)),
                "video_duration_seconds": round(
                    float(source.get("video_duration") or window), 1
                ),
                "speakable_seconds": round(speak_window, 1),
                "word_budget": word_budget,
                "importance": ns.get("importance", tl.get("importance", 0.5)),
            })

        polished_texts = await self._call_llm(payloads, style or {})
        if not polished_texts:
            logger.warning("NarrativePolisher: no LLM result — applying rule cleanup")
            polished_texts = self._rule_cleanup(payloads)

        out: list[dict[str, Any]] = []
        for ns in unified_segments:
            sid = str(ns.get("segment_id", ""))
            item = dict(ns)
            if sid in polished_texts and polished_texts[sid].strip():
                item["text"] = polished_texts[sid].strip()
                item["polished"] = True
            else:
                item["text"] = self._clean_one(str(item.get("text", "")))
                item["polished"] = False
            lang = ((style or {}).get("language") or "zh").strip().lower()
            item["text"] = sanitize_timeline_narration(
                str(item.get("text") or ""),
                room_type=str(item.get("room_type") or ""),
                language=lang,
            )
            out.append(item)

        logger.info(
            "NarrativePolisher: %d/%d segments polished",
            sum(1 for s in out if s.get("polished")),
            len(out),
        )
        return out

    async def _call_llm(
        self, payloads: list[dict], style: dict
    ) -> dict[str, str]:
        if self.llm_provider is None:
            return {}

        from backend.agents.script.utils import SCRIPT_LLM_MAX_TOKENS, safe_extract_json
        from backend.services.llm.base import LLMMessage

        prompt = _load_prompt(
            style_json=json.dumps(style, indent=2),
            segments_json=json.dumps(payloads, indent=2),
        )
        try:
            response = await self.llm_provider.generate(
                messages=[LLMMessage(role="user", content=prompt)],
                temperature=0.35,
                max_tokens=SCRIPT_LLM_MAX_TOKENS,
            )
        except Exception as exc:
            logger.warning("NarrativePolisher LLM failed: %s", exc)
            return {}

        data = safe_extract_json(getattr(response, "content", "") or "", fallback=[])
        results: dict[str, str] = {}
        for item in data if isinstance(data, list) else []:
            if not isinstance(item, dict):
                continue
            sid = str(item.get("segment_id", "")).strip()
            text = str(item.get("text", "")).strip()
            if sid and text:
                results[sid] = text
        return results

    def _rule_cleanup(self, payloads: list[dict]) -> dict[str, str]:
        """Deterministic de-dupe / fragment cleanup when LLM unavailable."""
        seen_phrases: set[str] = set()
        out: dict[str, str] = {}
        # Cross-segment banned repeats (normalized)
        global_seen: set[str] = set()

        for p in payloads:
            text = self._clean_one(str(p.get("text", "")))
            room = str(p.get("room_type", "")).lower()
            focus = " ".join(str(x).lower() for x in (p.get("focus_elements") or []))

            # Drop clauses that clearly don't belong to this room
            clauses = [c.strip() for c in re.split(r"[,;]", text) if c.strip()]
            kept: list[str] = []
            for c in clauses:
                cl = c.lower()
                # Kitchen language while not in kitchen
                if "kitchen" not in room and any(
                    k in cl for k in ("cabinet", "countertop", "stove", "range", "sink", "refrigerator")
                ):
                    if "kitchen" not in focus and "island" not in focus:
                        continue
                # Exterior language indoors
                if "exterior" not in room and any(
                    k in cl for k in ("brick facade", "black door", "yellow-trimmed")
                ):
                    continue

                key = re.sub(r"[^a-z0-9 ]+", "", cl).strip()
                # Skip near-duplicate short clauses already used in this tour
                if key in global_seen and len(c.split()) <= 8:
                    continue
                # Skip internal duplicates
                if key in seen_phrases:
                    continue
                seen_phrases.add(key)
                global_seen.add(key)
                kept.append(c)

            if not kept:
                kept = [text]

            rebuilt = ", ".join(kept)
            # Collapse "complete with X" stacking
            rebuilt = re.sub(
                r",?\s*complete with [^,.]+",
                "",
                rebuilt,
                flags=re.IGNORECASE,
            )
            rebuilt = self._clean_one(rebuilt)

            words = rebuilt.split()
            budget = int(p.get("word_budget", 20))
            if len(words) > budget:
                rebuilt = " ".join(words[:budget]).rstrip(",.;") + "."
            out[str(p["segment_id"])] = rebuilt
        return out

    @staticmethod
    def _clean_one(text: str) -> str:
        import re
        t = " ".join(text.split())
        t = t.replace(" / ", " ").replace("/", " ")
        # Fix truncated fragments
        t = re.sub(r"\bfrosted patterned\.?", "frosted patterned glass door", t, flags=re.I)
        t = re.sub(r"\ba stainless,?", "a stainless steel range", t, flags=re.I)
        t = re.sub(r"\s+,", ",", t)
        t = re.sub(r",\s*,+", ",", t)
        t = re.sub(r"\s{2,}", " ", t).strip(" ,;")
        if t and t[-1] not in ".!?":
            t += "."
        # Capitalize
        if t:
            t = t[0].upper() + t[1:]
        return t
