"""Full AI Director pipeline runner.

Phase 1  →  Planner + Script Agent          (initial narration)
Phase 2  →  Timeline Agent (first pass)     (estimated durations, no Voice yet)
Phase 3  →  Script Agent rewrite loop       (if FLAG_REWRITE segments exist)
              repeat up to MAX_REWRITE_ITER:
                  ScriptAgent.rewrite_for_timeline()
                  Timeline Agent (re-evaluate)
              until no FLAG_REWRITE or max iterations
Phase 4  →  Voice Agent                     (speech planning)
            Voice Execution Service         (TTS synthesis)
Phase 5  →  Timeline Agent (final pass)     (actual audio durations)

Voice is NEVER run before Timeline has approved the script.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import sys
from pathlib import Path
from urllib.parse import urlparse

import repo_paths  # noqa: F401  # puts system/ on sys.path
sys.path.insert(0, str(Path(__file__).parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

from backend.tools.property_workspace import DEFAULT_VIDEO_PATH, resolve_workspace
from backend.services.llm.config import openai_api_key, openai_base_url, openai_model

API_KEY = openai_api_key()
BASE_URL = openai_base_url()
LLM_MODEL = openai_model()
VOLCENGINE_API_KEY = os.environ.get("VOLCENGINE_API_KEY", "")
VOLCENGINE_ENDPOINT = "wss://openspeech.bytedance.com/api/v3/tts/bidirection"
VOLCENGINE_RESOURCE_ID = "seed-tts-1.0"

MAX_REWRITE_ITER = 2   # max Script↔Timeline rewrite rounds before giving up


def _infer_narration_language(prompt: str) -> str:
    """CLI default: Chinese prompt should produce Chinese narration."""
    text = prompt or ""
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    return "zh" if cjk >= 4 else "en"


def _timeline_rewrite_requests(timeline: dict, script: dict | None = None) -> list[dict]:
    """Build rewrite requests against the current canonical script IDs."""
    script_ids = {
        str(s.get("segment_id") or "")
        for s in (script or {}).get("narration_segments", []) or []
    }
    requests: list[dict] = []
    for tl_seg in (timeline or {}).get("segments", []) or []:
        dd = tl_seg.get("duration_decision") or {}
        if not dd.get("needs_script_rewrite"):
            continue
        safe_id = str(tl_seg.get("id", "")).split("[", 1)[0]
        source_ids = [safe_id] if safe_id in script_ids else (tl_seg.get("source_ids") or [])
        target_audio = float(
            dd.get("target_audio_duration")
            or max(
                0.0,
                float(dd.get("video_duration") or 0)
                - float(tl_seg.get("audio_offset") or 0)
                - 0.40,
            )
        )
        requests.append({
            "source_ids": source_ids,
            "video_duration": float(dd.get("video_duration") or 0),
            "audio_duration": float(dd.get("audio_duration") or 0),
            "target_audio_duration": target_audio,
        })
    return requests


def parse_args() -> tuple[str, Path, bool, int | None, bool]:
    """Returns (cli_prompt, video, skip_tts, max_tts_segments, force_ask).

    force_ask: --ask always prompts interactively (even if CLI text given).
    """
    args = sys.argv[1:]
    video_path = DEFAULT_VIDEO_PATH
    prompt_parts: list[str] = []
    skip_tts = False
    max_tts_segments: int | None = None
    force_ask = False
    i = 0
    while i < len(args):
        if args[i] == "--video" and i + 1 < len(args):
            video_path = Path(args[i + 1]); i += 2
        elif args[i] == "--skip-tts":
            skip_tts = True; i += 1
        elif args[i] == "--ask":
            force_ask = True; i += 1
        elif args[i] == "--max-segments" and i + 1 < len(args):
            max_tts_segments = int(args[i + 1]); i += 2
        elif args[i] == "--api-key" and i + 1 < len(args):
            global VOLCENGINE_API_KEY
            VOLCENGINE_API_KEY = args[i + 1]; i += 2
        else:
            prompt_parts.append(args[i]); i += 1
    prompt = " ".join(prompt_parts).strip()
    return prompt, video_path, skip_tts, max_tts_segments, force_ask


def _llm_reachable(base_url: str, timeout: float = 1.5) -> bool:
    parsed = urlparse(base_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 80
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


async def run_pipeline(
    user_prompt: str,
    video_path: Path,
    skip_tts: bool,
    max_tts_segments: int | None,
    intent_meta: dict | None = None,
) -> dict:
    from backend.agents.planner.agent import PlannerAgent
    from backend.agents.script.agent import ScriptAgent
    from backend.agents.timeline.agent import TimelineAgent
    from backend.schemas.planning_schema import planner_output_to_director_dict
    from backend.services.llm.openai_provider import OpenAIProvider
    from backend.state.project_state import ProjectState, UserGoal

    ws = resolve_workspace(video_path)

    if not ws.vkb_path.exists():
        raise FileNotFoundError(
            f"VKB not found at {ws.vkb_path}.\nRun vision pipeline first:\n  python3 run_vision_full.py"
        )

    with open(ws.vkb_path) as f:
        vkb_data = json.load(f)

    if not _llm_reachable(BASE_URL):
        raise RuntimeError(
            f"LLM server not reachable at {BASE_URL}.\n"
            "Scene Narrator requires LLM — start the server first."
        )
    llm = OpenAIProvider(api_key=API_KEY, base_url=BASE_URL, default_model=LLM_MODEL)

    intent_meta = intent_meta or {}
    ws.write_metadata(
        user_prompt=user_prompt,
        extra={"last_agent": "full_pipeline", **intent_meta},
    )

    state = ProjectState(
        project_id=ws.slug,
        user_goal=UserGoal(
            prompt=user_prompt,
            property_metadata=intent_meta,
        ),
        vision=vkb_data,
    )

    # ── Phase 1: Planner + Script ──────────────────────────────────────────
    print_phase(1, "Planner + Script Agent (initial narration)")
    state = await PlannerAgent(llm_provider=llm).run(state)
    # Persist Studio language choice onto planning intent for downstream agents.
    if isinstance(state.planning, dict):
        intent_block = state.planning.setdefault("intent", {})
        if isinstance(intent_block, dict):
            intent_block["narration_language"] = intent_meta.get("narration_language", "en")
    _save(ws.planner_output_path, planner_output_to_director_dict(state.planning))
    _save(ws.planner_output_full_path, state.planning)
    logger.info("Planner: %d HERO / %d TRANSITION",
        len(state.planning.get("hierarchy", {}).get("hero_segments", [])),
        len(state.planning.get("hierarchy", {}).get("transition_segments", [])))

    script_agent = ScriptAgent(llm_provider=llm)
    from backend.configs import agent_section
    timeline_agent = TimelineAgent(config=agent_section("timeline"))

    state = await script_agent.run(state)
    _save(ws.script_output_path, state.script)

    # ── Phase 2: Timeline first pass (estimated durations, no Voice yet) ──
    print_phase(2, "Timeline Agent — first pass (script estimated durations)")
    state = await timeline_agent.run(state)
    _save(ws.timeline_output_path, state.timeline)
    rewrite_requests = timeline_agent.extract_rewrite_requests(state.timeline)
    _report_timeline(state.timeline, rewrite_requests)

    # ── Phase 3: Script rewrite loop ──────────────────────────────────────
    iteration = 0
    while rewrite_requests and iteration < MAX_REWRITE_ITER:
        iteration += 1
        print_phase(
            f"3.{iteration}",
            f"Script Agent rewrite — iteration {iteration}/{MAX_REWRITE_ITER} "
            f"({len(rewrite_requests)} FLAG_REWRITE segments)",
        )
        state = await script_agent.rewrite_for_timeline(state, rewrite_requests)
        _save(ws.script_output_path, state.script)

        print_phase(f"3.{iteration}b", "Timeline Agent — re-evaluation after rewrite")
        state = await timeline_agent.run(state)
        _save(ws.timeline_output_path, state.timeline)
        rewrite_requests = timeline_agent.extract_rewrite_requests(state.timeline)
        _report_timeline(state.timeline, rewrite_requests)

    if rewrite_requests:
        logger.warning(
            "Still %d FLAG_REWRITE segments after %d rewrite iterations — proceeding anyway",
            len(rewrite_requests), MAX_REWRITE_ITER,
        )

    # ── Phase 3.5: Narration Unifier + Narrative Polisher ─────────────────
    # After Timeline merges, produce one unified narration per timeline segment.
    # Then LLM-polish the FULL tour for coherence / de-dupe / visual alignment.
    # Canonical script overwrite:
    #   timeline/timeline_script.json  AND  script/script_output.json
    print_phase("3.5", "Narration Unifier + Narrative Polisher")
    from backend.agents.timeline.pipeline.narration_unifier import NarrationUnifier
    from backend.agents.timeline.pipeline.narrative_polisher import NarrativePolisher

    unifier = NarrationUnifier(llm_provider=llm)
    polisher = NarrativePolisher(llm_provider=llm)
    # Preserve scene-level draft before overwrite (debug / audit only)
    if state.script and not state.script.get("unified_from_timeline"):
        _save(ws.script_draft_path, state.script)

    unified_segments = await unifier.unify(
        timeline=state.timeline,
        script=state.script,
        vkb=state.vision,
    )
    unified_segments = await polisher.polish(
        unified_segments,
        timeline=state.timeline,
        style=state.script.get("style", {}),
    )

    # Guard: Kitchen+Bathroom inventory must not be dropped by polish.
    from backend.agents.script.pipeline.marketing_enricher import (
        dedupe_generic_atmosphere,
        ensure_timeline_space_coverage,
    )

    polish_lang = (state.script.get("style") or {}).get("language") or "zh"
    unified_segments = ensure_timeline_space_coverage(
        unified_segments,
        state.vision,
        language=polish_lang,
    )
    # Same-type rooms must not all be sold as "dark floors, white walls, big window".
    unified_segments = dedupe_generic_atmosphere(unified_segments, language=polish_lang)

    from backend.agents.timeline.pipeline.tour_trust_guard import apply_tour_trust_guard

    unified_segments, guarded_timeline, trust_fixes = apply_tour_trust_guard(
        unified_segments,
        timeline=state.timeline,
        vkb=state.vision,
        language=polish_lang,
    )
    if trust_fixes:
        logger.info("Tour Trust Guard applied %d fix(es)", len(trust_fixes))
        state_dict = state.model_dump()
        state_dict["timeline"] = guarded_timeline
        state = ProjectState(**state_dict)

    merged_segs = [s for s in unified_segments if s.get("is_merged")]
    logger.info(
        "Unified+polished narration: %d timeline segments | %d merged groups",
        len(unified_segments), len(merged_segs),
    )

    # Inject unified narration into state as the canonical script
    unified_script = dict(state.script)
    unified_script["narration_segments"] = unified_segments
    unified_script["segment_count"] = len(unified_segments)
    unified_script["unified_from_timeline"] = True
    unified_script["polished"] = True
    _save(ws.timeline_script_path, unified_script)
    _save(ws.script_output_path, unified_script)  # overwrite — source of truth
    logger.info(
        "Canonical script overwritten: %s (%d segments)",
        ws.script_output_path.name, len(unified_segments),
    )

    state_dict = state.model_dump()
    state_dict["script"] = unified_script
    from backend.state.project_state import ProjectState as PS
    state = PS(**state_dict)

    trust_rewrite_requests = _timeline_rewrite_requests(state.timeline, state.script)
    if trust_rewrite_requests:
        print_phase(
            "3.6",
            f"Tour Trust Guard rewrite — {len(trust_rewrite_requests)} flagged segments",
        )
        state = await script_agent.rewrite_for_timeline(state, trust_rewrite_requests)
        rechecked_segments, rechecked_timeline, recheck_fixes = apply_tour_trust_guard(
            state.script.get("narration_segments", []) or [],
            timeline=state.timeline,
            vkb=state.vision,
            language=polish_lang,
        )
        if recheck_fixes:
            logger.info("Tour Trust Guard post-rewrite applied %d fix(es)", len(recheck_fixes))
            state_dict = state.model_dump()
            script_data = dict(state.script)
            script_data["narration_segments"] = rechecked_segments
            script_data["segment_count"] = len(rechecked_segments)
            state_dict["script"] = script_data
            state_dict["timeline"] = rechecked_timeline
            state = PS(**state_dict)
        _save(ws.script_output_path, state.script)
        _save(ws.timeline_script_path, state.script)

    # ── Phase 4: Voice Agent (now Timeline has approved the script) ────────
    print_phase(4, f"Voice Agent — {len(unified_segments)} timeline segments")
    from backend.agents.voice.agent import VoiceAgent
    state = await VoiceAgent().run(state)
    _save(ws.voice_plan_path, state.voice)

    if not skip_tts and VOLCENGINE_API_KEY:
        print_phase("4b", "Voice Execution Service (TTS synthesis — one file per timeline segment)")
        from backend.schemas.voice_schema import VoicePlan
        from backend.services.voice_executor import VoiceExecutionService

        # Remove stale audio files from previous runs that used the old
        # per-scene naming (seg_01.mp3 ... seg_15.mp3).  New naming is
        # per-timeline-segment (tl_001.mp3 ... tl_010.mp3).
        stale = list(ws.audio_dir.glob("seg_*.mp3"))
        if stale:
            for f in stale:
                f.unlink()
            logger.info("Removed %d stale seg_*.mp3 files from audio dir", len(stale))

        voice_plan_data = state.voice.get("voice_plan", state.voice)
        plan = VoicePlan.model_validate(voice_plan_data)
        if max_tts_segments is not None:
            plan.segments = plan.segments[:max_tts_segments]
            logger.info("Limiting TTS to first %d segments", max_tts_segments)

        executor = VoiceExecutionService(
            api_key=VOLCENGINE_API_KEY,
            endpoint=VOLCENGINE_ENDPOINT,
            resource_id=VOLCENGINE_RESOURCE_ID,
            default_speaker=plan.profile.voice_id,
        )
        execution = await executor.synthesize_plan(plan, ws.audio_dir, project_id=ws.slug)
        exec_data = execution.model_dump(mode="json")
        _save(ws.voice_execution_path, exec_data)

        # Merge execution results back into state.voice for final Timeline pass
        state_dict = state.model_dump()
        merged_voice = dict(state.voice)
        merged_voice.update(exec_data)
        state_dict["voice"] = merged_voice
        state = PS(**state_dict)
        logger.info("TTS: %d segments synthesized | total=%.1fs", len(execution.segments), execution.total_duration)
    else:
        if skip_tts:
            logger.info("TTS skipped (--skip-tts)")
        else:
            logger.warning("VOLCENGINE_API_KEY not set — TTS execution skipped")

    # ── Phase 5: Timeline final refine (actual audio durations, no re-merge) ─
    print_phase(5, "Timeline Agent — refine with actual audio (no re-merge)")
    state = await timeline_agent.refine_with_audio(state)
    _save(ws.timeline_output_path, state.timeline)
    _report_timeline(state.timeline, [])

    # ── Phase 5.5: Post-TTS sync guard ─────────────────────────────────────
    # refine_with_audio flags segments whose MEASURED audio would force
    # playback below 0.5× (near-freeze slow-motion = perceived A/V desync).
    # Before this phase existed the flag was set but never acted on.
    # Here we compress those narrations, re-synthesize ONLY them, and refine
    # the timeline once more.
    if not skip_tts and VOLCENGINE_API_KEY:
        flagged = _timeline_rewrite_requests(state.timeline, state.script)
        if flagged:
            print_phase(
                "5.5",
                f"Post-TTS sync guard — {len(flagged)} segments below 0.5× playback, "
                "compressing narration + re-synthesizing",
            )
            from backend.agents.voice.agent import VoiceAgent
            from backend.schemas.voice_schema import VoicePlan
            from backend.services.voice_executor import VoiceExecutionService
            from backend.state.project_state import ProjectState as PS

            prev_exec_segments = {
                str(s.get("script_id") or s.get("segment_id") or ""): s
                for s in (state.voice or {}).get("segments", []) or []
            }

            state = await script_agent.rewrite_for_timeline(state, flagged)
            rechecked_segments, rechecked_timeline, recheck_fixes = apply_tour_trust_guard(
                state.script.get("narration_segments", []) or [],
                timeline=state.timeline,
                vkb=state.vision,
                language=polish_lang,
            )
            if recheck_fixes:
                logger.info(
                    "Tour Trust Guard post-TTS rewrite applied %d fix(es)",
                    len(recheck_fixes),
                )
                state_dict = state.model_dump()
                script_data = dict(state.script)
                script_data["narration_segments"] = rechecked_segments
                script_data["segment_count"] = len(rechecked_segments)
                state_dict["script"] = script_data
                state_dict["timeline"] = rechecked_timeline
                state = PS(**state_dict)
            _save(ws.script_output_path, state.script)
            _save(ws.timeline_script_path, state.script)

            state = await VoiceAgent().run(state)
            voice_plan_data = state.voice.get("voice_plan", state.voice)
            replan = VoicePlan.model_validate(voice_plan_data)
            wanted = {req["source_ids"][0] for req in flagged}
            replan.segments = [
                s for s in replan.segments
                if (s.script_id or s.id).split("[", 1)[0] in wanted
            ]
            resync_executor = VoiceExecutionService(
                api_key=VOLCENGINE_API_KEY,
                endpoint=VOLCENGINE_ENDPOINT,
                resource_id=VOLCENGINE_RESOURCE_ID,
                default_speaker=replan.profile.voice_id,
            )
            re_execution = await resync_executor.synthesize_plan(
                replan, ws.audio_dir, project_id=ws.slug
            )
            for seg_data in re_execution.model_dump(mode="json").get("segments", []):
                key = str(seg_data.get("script_id") or seg_data.get("segment_id") or "")
                prev_exec_segments[key] = seg_data

            state_dict = state.model_dump()
            merged_voice = dict(state.voice)
            merged_voice["segments"] = list(prev_exec_segments.values())
            state_dict["voice"] = merged_voice
            state = PS(**state_dict)
            _save(ws.voice_execution_path, {
                "agent_name": "voice_execution",
                "resynced_segments": sorted(wanted),
                "segments": merged_voice["segments"],
                "total_duration": round(
                    sum(float(s.get("duration") or 0) for s in merged_voice["segments"]), 2
                ),
            })

            state = await timeline_agent.refine_with_audio(state)
            _save(ws.timeline_output_path, state.timeline)
            _report_timeline(state.timeline, [])

            still = [
                s for s in (state.timeline or {}).get("segments", [])
                if (s.get("duration_decision") or {}).get("needs_script_rewrite")
            ]
            if still:
                logger.warning(
                    "Post-TTS sync guard: %d segments still below 0.5× after rewrite "
                    "— proceeding (renderer will slow-mo)",
                    len(still),
                )

    logger.info("Full pipeline complete: %s", ws.slug)
    return {
        "workspace": ws,
        "script": state.script,
        "voice": state.voice,
        "timeline": state.timeline,
    }


def _save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


def print_phase(num, desc: str) -> None:
    print(f"\n{'─' * 68}")
    print(f"  Phase {num}: {desc}")
    print(f"{'─' * 68}")


def _report_timeline(tl: dict, rewrite_requests: list[dict]) -> None:
    segs = tl.get("segments", [])
    val = tl.get("validation", {})
    flags = [r["timeline_segment_id"] for r in rewrite_requests]
    logger.info(
        "Timeline: %d segments | %.1fs | merges=%d | valid=%s | rewrites=%d %s",
        len(segs),
        tl.get("total_duration", 0),
        tl.get("merge_count", 0),
        val.get("is_valid"),
        len(flags),
        flags or "",
    )


def print_final(result: dict) -> None:
    ws = result["workspace"]
    tl = result["timeline"]
    segs = tl.get("segments", [])
    val = tl.get("validation", {})

    print("\n" + "=" * 72)
    print(f"FULL PIPELINE COMPLETE — {ws.slug}")
    print("=" * 72)
    print(f"\n  Script:    {ws.script_output_path}  (timeline-aligned, canonical)")
    print(f"  TL Script: {ws.timeline_script_path}")
    print(f"  Draft:     {ws.script_draft_path}  (pre-merge scene-level, if saved)")
    print(f"  Voice:     {ws.voice_plan_path}")
    print(f"  Audio:     {ws.audio_dir}")
    print(f"  Timeline:  {ws.timeline_output_path}")
    print(f"\n  Timeline:  {len(segs)} segments | {tl.get('total_duration', 0):.1f}s total")
    print(f"  Merges:    {tl.get('merge_count', 0)}")
    print(f"  Validation: {'PASS' if val.get('is_valid') else 'ISSUES'}")
    for issue in val.get("issues", []):
        print(f"    ⚠ {issue}")
    hero_coverage = val.get("must_show_coverage", {})
    print(f"  HERO coverage: {sum(hero_coverage.values())}/{len(hero_coverage)} ✓")


if __name__ == "__main__":
    from backend.workflows.user_intent import resolve_user_intent

    cli_prompt, video, skip_tts, max_segs, force_ask = parse_args()
    lang = _infer_narration_language(cli_prompt)
    # Always resolve intent: interactive ask when TTY / --ask; vague → default
    # space / facilities / light coverage prompt.
    resolved = resolve_user_intent(
        cli_prompt,
        interactive=True if force_ask else None,
        language=lang,
    )
    lang = _infer_narration_language(resolved.prompt)
    intent_meta = {
        "intent_source": resolved.source,
        "intent_was_vague": resolved.was_vague,
        "intent_original": resolved.original_prompt,
        "narration_language": lang,
    }

    print(f"\nProperty video: {video.name}")
    print(f"Director intent ({resolved.source}): \"{resolved.prompt[:120]}\"")
    if resolved.was_vague and resolved.original_prompt:
        print(f"  (original vague input: \"{resolved.original_prompt}\")")

    result = asyncio.run(
        run_pipeline(resolved.prompt, video, skip_tts, max_segs, intent_meta)
    )
    print_final(result)
