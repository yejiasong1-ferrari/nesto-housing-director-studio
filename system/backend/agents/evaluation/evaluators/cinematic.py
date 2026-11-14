"""Cinematic Quality Evaluator — 15% weight (rules + optional LLM)."""

from __future__ import annotations

from typing import Any

from backend.agents.evaluation.evaluators._helpers import clamp_score, safe_id
from backend.schemas.evaluation_schema import EvaluationIssue


class CinematicEvaluator:
    weight = 0.15

    def evaluate(
        self,
        timeline: dict[str, Any],
        editing: dict[str, Any],
        planning: dict[str, Any],
    ) -> tuple[float, list[EvaluationIssue]]:
        issues: list[EvaluationIssue] = []
        penalties = 0.0

        hero_ids = set(planning.get("hierarchy", {}).get("hero_segments", []) or [])
        edit_by = {
            safe_id(s.get("segment_id", "")): s
            for s in (editing.get("segments") or [])
        }

        hero_count = 0
        hero_emphasized = 0
        for tl in timeline.get("segments") or []:
            sid = safe_id(tl.get("id", ""))
            source_ids = set(tl.get("source_ids") or [])
            is_hero = tl.get("role") == "HERO" or bool(source_ids & hero_ids)
            if not is_hero:
                continue
            hero_count += 1
            edit = edit_by.get(sid, {})
            ops = (
                edit.get("visual_strategy", {}).get("operations")
                or edit.get("visual_strategies")
                or []
            )
            types = [str(o.get("type", "")).lower() for o in ops]
            if any(t in ("slow_zoom", "zoom", "ken_burns", "slow_motion") for t in types):
                hero_emphasized += 1
            else:
                issues.append(EvaluationIssue(
                    type="hero_underemphasized",
                    segment_id=sid,
                    severity="medium",
                    description=f"Hero '{sid}' uses flat cut — lacks cinematic emphasis",
                    evidence={"ops": types},
                    suggested_target="editing",
                ))
                penalties += 12

        # Too many identical effects can feel mechanical
        all_ops = []
        for e in editing.get("segments") or []:
            ops = e.get("visual_strategy", {}).get("operations") or e.get("visual_strategies") or []
            all_ops.extend(str(o.get("type", "")) for o in ops)
        if all_ops and len(set(all_ops)) == 1 and all_ops[0] not in ("clean_cut", ""):
            issues.append(EvaluationIssue(
                type="cinematic_monotony",
                segment_id="",
                severity="low",
                description=f"All segments use the same effect '{all_ops[0]}'",
                evidence={"effect": all_ops[0]},
                suggested_target="editing",
            ))
            penalties += 6

        if hero_count == 0:
            penalties += 8
            issues.append(EvaluationIssue(
                type="hero_underemphasized",
                segment_id="",
                severity="medium",
                description="No HERO segments found in timeline",
                evidence={},
                suggested_target="timeline",
            ))

        return clamp_score(100.0 - penalties), issues
