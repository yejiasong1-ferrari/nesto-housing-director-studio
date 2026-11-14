"""Primary-room onset: when this shot's main space becomes confirmable.

Vision segments answer "which rooms appeared in this clip". Script and
Timeline need "from which second is the primary room on camera".

This module writes ``VKBSegment.room_visible_start`` (absolute seconds).
Downstream: ``audio_offset = max(0, visible_start − segment_start)``.

Conservative by design: prefer ~0.3s late over 2s early. If CLIP cannot
confirm a later onset, leave ``visible_start = segment_start`` — never
invent a delay. Open-plan glimpses (seeing a stove from the living room)
do not count as having entered the kitchen.
"""

from __future__ import annotations

import logging
from typing import Any, Optional, Protocol

from backend.schemas.vision_schema import VKBSegment, VisionKnowledgeBase

logger = logging.getLogger(__name__)

# Prefer speaking a bit late rather than naming a room that is not yet the shot.
CONSERVATIVE_LAG = 0.30
# Primary must beat the previous room by this cosine margin.
DEFAULT_MARGIN = 0.04
# Living↔kitchen (and similar) need a clearer win — a glimpse is not entry.
OPEN_PLAN_MARGIN = 0.08
# Ignore very weak CLIP matches; don't invent an onset from noise.
ABS_MIN_SCORE = 0.18
# Never push onset past this fraction of the segment (need a speak window).
MAX_ONSET_FRACTION = 0.35
# Absolute ceiling on head silence. Beyond this the shot reads as dead air and
# the narration has to be compressed to fit what is left.
MAX_ONSET_SECONDS = 2.50
# Bedroom / bathroom approached down a hallway: 2.5s still leaves the camera
# in the corridor. Living / kitchen stay on the short cap so the open hall
# does not go back to 8s of dead air.
HALL_APPROACH_MAX_ONSET = 4.00
# Open plan: CLIP cannot separate "walking toward the kitchen" from "in the
# kitchen", so its late onset is usually wrong. Trust it far less here.
OPEN_PLAN_MAX_ONSET = 1.50
_HALL_APPROACH_ROOMS = frozenset({"Bedroom", "Bathroom"})
# Consecutive cuts in the same room — the camera is already inside.
SAME_ROOM_MAX_ONSET = 0.80
MIN_SPEAK_WINDOW = 1.20
# The segmenter already decided this whole span is one room. If CLIP claims the
# room is on camera for less than this share of the shot, CLIP lost the room
# (reflections, tight framing, open plan) — widen rather than believe it.
MIN_VISIBLE_FRACTION = 0.45

OPEN_PLAN_PAIRS = frozenset(
    {
        frozenset({"Living Room", "Kitchen"}),
        frozenset({"Living Room", "Dining Room"}),
        frozenset({"Kitchen", "Dining Room"}),
    }
)

# CLIP text prompts: "is the camera in this room", not "does this object appear".
ROOM_TEXT_PROMPTS: dict[str, str] = {
    "Kitchen": "a photo of the interior of a residential kitchen, standing in the kitchen",
    "Living Room": "a photo of a living room interior with a sofa, standing in the living room",
    "Bedroom": "a photo of a bedroom interior with a bed, standing in the bedroom",
    "Bathroom": "a photo of a bathroom interior with a toilet or shower, standing in the bathroom",
    "Laundry Room": "a photo of a laundry room with a washing machine, standing in the laundry",
    "Study Room": "a photo of a home office or study with a desk, standing in the study",
    "Dining Room": "a photo of a dining room interior with a dining table",
    "Hallway": "a photo of a residential hallway or corridor",
    "Balcony": "a photo of a residential balcony",
    "Closet": "a photo of a walk-in closet or wardrobe room",
}

_NO_DELAY_TYPES = frozenset({"Hallway", "Unknown", "Mixed Private Area", "Corridor"})
_PRIVATE_ROOMS = frozenset({
    "Bedroom", "Bathroom", "Laundry Room", "Study Room", "Closet", "Kitchen",
})
_APPROACH_COMPETITORS = ("Hallway", "Living Room", "Corridor")


class RoomImageScorer(Protocol):
    """Score an image embedding against a room-type prompt."""

    def compute_embedding(self, image_path: str) -> Any: ...

    def score_image_text(self, image_embedding: Any, text: str) -> float: ...


def relative_audio_offset(
    segment_start: float,
    segment_end: float,
    room_visible_start: float,
) -> float:
    """Seconds after segment start when narration may begin. Never negative."""
    start = float(segment_start or 0.0)
    end = float(segment_end or start)
    vis = float(room_visible_start or 0.0)
    if vis <= 0.0 and start > 0.5:
        return 0.0
    vis = max(start, vis)
    if end > start:
        vis = min(vis, end)
    return round(max(0.0, vis - start), 3)


def resolve_visible_end(
    segment_start: float,
    segment_end: float,
    room_visible_end: float,
) -> float:
    """Absolute time the primary room is last still the shot."""
    start = float(segment_start or 0.0)
    end = float(segment_end or start)
    vis = float(room_visible_end or 0.0)
    if vis <= 0.0:
        return end
    return round(min(max(vis, start), end), 3)


def compute_room_stage(offset: float, *, left_early: bool = False) -> str:
    """approaching / entrance / interior / exiting from onset + exit."""
    off = float(offset or 0.0)
    if left_early and off < 0.45:
        return "exiting"
    if off >= 1.2:
        return "approaching"
    if off >= 0.45:
        return "entrance"
    return "interior"


def _norm_room(label: str) -> str:
    text = (label or "").strip()
    aliases = {
        "study": "Study Room",
        "study room": "Study Room",
        "study area": "Study Room",
        "guest bedroom": "Bedroom",
        "primary bedroom": "Bedroom",
        "secondary bedroom": "Bedroom",
        "bedroom area": "Bedroom",
        "laundry": "Laundry Room",
        "living": "Living Room",
        "bath": "Bathroom",
        "bathroom": "Bathroom",
    }
    return aliases.get(text.lower(), text)


def _primary_room(seg: VKBSegment) -> str:
    for space in seg.knowledge.spaces or []:
        if (space.room_role or "") == "primary":
            return _norm_room(space.type or seg.knowledge.room_type)
    return _norm_room(seg.knowledge.room_type or "")


def _is_open_plan(prev: str, current: str) -> bool:
    if not prev or not current or prev == current:
        return False
    return frozenset({prev, current}) in OPEN_PLAN_PAIRS


def onset_cap_seconds(
    duration: float,
    *,
    open_plan: bool = False,
    same_room: bool = False,
    from_hallway: bool = False,
) -> float:
    """Largest head silence we allow for this shot.

    Delaying narration is only worth it when a short wait buys a correct
    room. A long wait costs the line itself: whatever is left of the shot
    has to hold the whole sentence, which forces compression.
    """
    span = max(0.0, float(duration))
    cap = HALL_APPROACH_MAX_ONSET if from_hallway else MAX_ONSET_SECONDS
    if open_plan:
        cap = min(cap, OPEN_PLAN_MAX_ONSET)
    if same_room:
        cap = min(cap, SAME_ROOM_MAX_ONSET)
    return max(0.0, min(cap, max(MAX_ONSET_FRACTION * span, 0.5)))


def enforce_speak_window(
    segment_start: float,
    segment_end: float,
    visible_start: float,
    visible_end: float,
) -> tuple[float, float]:
    """Guarantee a usable window between onset and exit.

    Onset and exit are scored independently, so they can meet or cross —
    telling downstream to fit a full sentence into zero seconds. That is
    what forced narration compression on almost every shot. Prefer opening
    the window (speak slightly early / finish slightly late) over leaving
    no room to speak at all.
    """
    start = float(segment_start)
    end = max(start, float(segment_end))
    span = end - start
    vis = min(max(float(visible_start or start), start), end)
    vis_end = min(max(float(visible_end or end), vis), end)

    want = min(max(MIN_SPEAK_WINDOW, MIN_VISIBLE_FRACTION * span), span)
    if vis_end - vis >= want:
        return round(vis, 3), round(vis_end, 3)

    # Hold the onset, push the exit later first — speaking early is the
    # thing we were trying to avoid in the first place.
    vis_end = min(end, vis + want)
    if vis_end - vis < want:
        vis = max(start, vis_end - want)
    return round(vis, 3), round(vis_end, 3)


def compute_room_visible_start(
    segment_start: float,
    segment_end: float,
    frame_times: list[float],
    primary_scores: list[float],
    previous_scores: Optional[list[float]] = None,
    *,
    open_plan: bool = False,
    same_room: bool = False,
    from_hallway: bool = False,
) -> float:
    """First in-segment time the primary room clearly wins.

    Same-label as the previous cut does NOT skip this check — the camera may
    still be approaching, but it gets a much tighter cap. If scores never
    confirm a later onset, return ``segment_start``.
    """
    start = float(segment_start)
    end = float(segment_end)
    duration = max(0.0, end - start)
    if duration <= 0 or not frame_times or not primary_scores:
        return start

    margin = OPEN_PLAN_MARGIN if open_plan else DEFAULT_MARGIN
    n = min(len(frame_times), len(primary_scores))
    confirmed: Optional[float] = None
    for i in range(n):
        t = float(frame_times[i])
        if t < start - 0.05 or t >= end + 0.05:
            continue
        pscore = float(primary_scores[i])
        if pscore < ABS_MIN_SCORE:
            continue
        if previous_scores is not None and i < len(previous_scores):
            if pscore < float(previous_scores[i]) + margin:
                continue
        confirmed = max(start, t)
        break

    if confirmed is None:
        return start

    # Only lag when we actually waited into the segment — first-frame wins stay put.
    vis = confirmed
    if confirmed > start + 0.5:
        vis = confirmed + CONSERVATIVE_LAG

    max_t = start + onset_cap_seconds(
        duration,
        open_plan=open_plan,
        same_room=same_room,
        from_hallway=from_hallway,
    )
    if duration > MIN_SPEAK_WINDOW:
        max_t = min(max_t, end - MIN_SPEAK_WINDOW)
    max_t = max(start, min(max_t, end))
    return round(min(max(vis, start), max_t), 3)


def compute_room_visible_end(
    segment_start: float,
    segment_end: float,
    frame_times: list[float],
    primary_scores: list[float],
    next_scores: Optional[list[float]] = None,
    *,
    open_plan: bool = False,
) -> float:
    """Last in-segment time the primary room still clearly wins.

    Unset competitor / still winning at the last frame → ``segment_end``.
    Prefer an earlier cutoff over speaking after the camera has left.
    """
    start = float(segment_start)
    end = float(segment_end)
    if end <= start or not frame_times or not primary_scores:
        return end

    margin = OPEN_PLAN_MARGIN if open_plan else DEFAULT_MARGIN
    n = min(len(frame_times), len(primary_scores))
    last_win: Optional[float] = None
    last_t = start
    for i in range(n):
        t = float(frame_times[i])
        if t < start - 0.05 or t >= end + 0.05:
            continue
        last_t = t
        pscore = float(primary_scores[i])
        if pscore < ABS_MIN_SCORE:
            continue
        if next_scores is not None and i < len(next_scores):
            if pscore < float(next_scores[i]) + margin:
                continue
        last_win = max(start, t)

    if last_win is None:
        return end
    vis = last_win
    if last_win < last_t - 0.5:
        vis = max(start, last_win - CONSERVATIVE_LAG)
    else:
        vis = end
    vis = min(vis, end)
    vis = max(vis, min(start + MIN_SPEAK_WINDOW, end))
    return round(vis, 3)


def _frames_in_segment(
    frames: list[dict[str, Any]],
    start: float,
    end: float,
) -> list[dict[str, Any]]:
    out = []
    for frame in frames or []:
        t = float(frame.get("timestamp", 0.0) or 0.0)
        path = frame.get("frame_path") or frame.get("path") or ""
        if start - 0.05 <= t < end + 0.05 and path:
            out.append(frame)
    return out


def _score_frames(
    scorer: RoomImageScorer,
    frames: list[dict[str, Any]],
    room_type: str,
) -> list[float]:
    prompt = ROOM_TEXT_PROMPTS.get(room_type) or f"a photo of a {room_type.lower()} interior"
    scores: list[float] = []
    for frame in frames:
        path = str(frame.get("frame_path") or frame.get("path") or "")
        try:
            emb = scorer.compute_embedding(path)
            scores.append(scorer.score_image_text(emb, prompt))
        except Exception:
            logger.debug("room_onset: failed to score %s", path, exc_info=True)
            scores.append(0.0)
    return scores


def _max_scores(*score_lists: Optional[list[float]]) -> Optional[list[float]]:
    filled = [s for s in score_lists if s]
    if not filled:
        return None
    n = min(len(s) for s in filled)
    return [max(s[i] for s in filled) for i in range(n)]


def annotate_room_visible_starts(
    vkb: VisionKnowledgeBase,
    frames: list[dict[str, Any]],
    scorer: Optional[RoomImageScorer] = None,
) -> VisionKnowledgeBase:
    """Set ``room_visible_start`` / ``room_visible_end`` / ``room_stage``."""
    segments = list(vkb.segments or [])
    if not segments:
        return vkb

    prev_room = ""
    for i, seg in enumerate(segments):
        start = float(seg.raw.start_time or 0.0)
        end = float(seg.raw.end_time or start)
        primary = _primary_room(seg)
        vis = start
        vis_end = end
        next_room = _primary_room(segments[i + 1]) if i + 1 < len(segments) else ""

        if (
            scorer is not None
            and primary
            and primary not in _NO_DELAY_TYPES
            and frames
        ):
            in_frames = _frames_in_segment(frames, start, end)
            if in_frames:
                times = [float(f.get("timestamp", 0.0) or 0.0) for f in in_frames]
                primary_scores = _score_frames(scorer, in_frames, primary)
                competitor_lists: list[list[float]] = []
                if prev_room and prev_room != primary:
                    competitor_lists.append(_score_frames(scorer, in_frames, prev_room))
                if primary in _PRIVATE_ROOMS:
                    for comp in _APPROACH_COMPETITORS:
                        if comp != primary:
                            competitor_lists.append(_score_frames(scorer, in_frames, comp))
                prev_scores = _max_scores(*competitor_lists)
                vis = compute_room_visible_start(
                    start,
                    end,
                    times,
                    primary_scores,
                    prev_scores,
                    open_plan=_is_open_plan(prev_room, primary),
                    same_room=bool(prev_room and prev_room == primary),
                    from_hallway=primary in _HALL_APPROACH_ROOMS,
                )
                leave_lists: list[list[float]] = []
                if next_room and next_room != primary:
                    leave_lists.append(_score_frames(scorer, in_frames, next_room))
                if next_room != "Hallway":
                    leave_lists.append(_score_frames(scorer, in_frames, "Hallway"))
                next_scores = _max_scores(*leave_lists)
                vis_end = compute_room_visible_end(
                    start,
                    end,
                    times,
                    primary_scores,
                    next_scores,
                    open_plan=_is_open_plan(primary, next_room),
                )

        vis, vis_end = enforce_speak_window(start, end, vis, vis_end)
        offset = relative_audio_offset(start, end, vis)
        left_early = vis_end < end - 0.4
        seg.room_visible_start = round(vis, 3)
        seg.room_visible_end = round(vis_end, 3)
        seg.room_stage = compute_room_stage(offset, left_early=left_early)
        logger.info(
            "room_visible %s %s: start=%.2f visible=%.2f end=%.2f stage=%s offset=%.2f",
            seg.segment_id,
            primary or "?",
            start,
            vis,
            vis_end,
            seg.room_stage,
            offset,
        )
        prev_room = primary or prev_room

    return vkb


def finalize_vision_knowledge(
    vkb: VisionKnowledgeBase,
    frames: list[dict[str, Any]],
    scorer: Optional[RoomImageScorer] = None,
) -> VisionKnowledgeBase:
    """Verified-space gates, then primary-room onset. Call once at end of Vision."""
    from backend.agents.vision.modules.space_evidence_validator import validate_verified_vkb

    vkb = validate_verified_vkb(vkb)
    try:
        vkb = annotate_room_visible_starts(vkb, frames, scorer)
    except Exception:
        logger.exception("room_visible_start failed; falling back to segment starts")
        for seg in vkb.segments or []:
            if not seg.room_visible_start:
                seg.room_visible_start = float(seg.raw.start_time or 0.0)
            if not seg.room_visible_end:
                seg.room_visible_end = float(seg.raw.end_time or 0.0)
            if not seg.room_stage:
                seg.room_stage = "interior"
    return vkb
