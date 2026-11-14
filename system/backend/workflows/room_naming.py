"""Room Naming Normalization Layer — before Planner.

Vision invents stable instance IDs (Bedroom_4, Kitchen_2) for inventory
tracking. Downstream agents must never speak those numbers.

This layer rewrites each SpaceInventoryItem with:
  - instance_id   — internal DB key (kept / filled if missing)
  - display_name  — UI label without instance numbers
  - narration_name — Script-only speakable name
  - room_role     — primary | secondary | shared | utility | transit | amenity

Idempotent: safe to run on every Planner / Script VKB load.
"""

from __future__ import annotations

import logging
import re
from typing import Iterable

from backend.schemas.vision_schema import SpaceInventoryItem, VKBSegment, VisionKnowledgeBase

logger = logging.getLogger(__name__)

PRIMARY_EVIDENCE = (
    "master",
    "primary",
    "ensuite",
    "en-suite",
    "en suite",
    "walk-in",
    "walk in closet",
    "king bed",
    "king-size",
    "主卧",
    "主人房",
    "套房",
)

GUEST_EVIDENCE = ("guest", "客卧", "客房")
BED_EVIDENCE = ("bed", "headboard", "mattress", "duvet", "bedding", "床")

# Canonical type → (display_name, narration_name, default_role)
_TYPE_DEFAULTS: dict[str, tuple[str, str, str]] = {
    "Kitchen": ("Kitchen", "Kitchen", "shared"),
    "Living Room": ("Living Room", "Living Room", "shared"),
    "Dining Room": ("Dining Room", "Dining Room", "shared"),
    "Bathroom": ("Bathroom", "Bathroom", "utility"),
    "Hallway": ("Hallway", "Hallway", "transit"),
    "Balcony": ("Balcony", "Balcony", "amenity"),
    "Laundry Room": ("Laundry", "Laundry", "utility"),
    "Closet": ("Closet", "Closet", "utility"),
    "Study Room": ("Study Area", "Study Area", "secondary"),
    "Bedroom": ("Bedroom", "Bedroom", "secondary"),
}


def _slug_type(space_type: str) -> str:
    return re.sub(r"\s+", "_", (space_type or "Unknown").strip()) or "Unknown"


def make_instance_id(space_type: str, instance: int) -> str:
    """Stable internal id, e.g. Bedroom_4."""
    return f"{_slug_type(space_type)}_{max(int(instance or 1), 1)}"


def _feature_blob(space: SpaceInventoryItem) -> str:
    return " ".join(str(f) for f in (space.features or [])).lower()


def _has_evidence(space: SpaceInventoryItem, keywords: Iterable[str]) -> bool:
    blob = _feature_blob(space)
    type_l = (space.type or "").lower()
    hay = f"{blob} {type_l}"
    return any(k in hay for k in keywords)


def _has_bed(space: SpaceInventoryItem) -> bool:
    """Guest/bedroom rank labels require a bed in features or hard evidence."""
    blob = _feature_blob(space)
    ev = getattr(space, "evidence", None)
    if ev is not None:
        blob = f"{blob} {' '.join(str(f) for f in (ev.hard_features or []))}"
    hay = blob.lower()
    return any(k in hay for k in BED_EVIDENCE)


def _collect_unique_spaces(segments: list[VKBSegment]) -> list[SpaceInventoryItem]:
    """First-seen unique spaces by instance_id (or type+instance fallback)."""
    seen: dict[str, SpaceInventoryItem] = {}
    ordered: list[SpaceInventoryItem] = []
    for seg in sorted(segments, key=lambda s: s.raw.start_time):
        for space in seg.knowledge.spaces or []:
            key = (space.instance_id or "").strip() or make_instance_id(
                space.type, space.instance
            )
            if key in seen:
                # Prefer richer feature evidence
                prev = seen[key]
                if len(space.features or []) > len(prev.features or []):
                    seen[key] = space
                    # keep order; update reference later via rewrite map
                continue
            seen[key] = space
            ordered.append(space)
    # Refresh ordered refs after possible upgrades
    return [seen[(s.instance_id or make_instance_id(s.type, s.instance))] for s in ordered]


def _pick_primary_bedroom(bedrooms: list[SpaceInventoryItem]) -> SpaceInventoryItem | None:
    if not bedrooms:
        return None
    evidenced = [b for b in bedrooms if _has_evidence(b, PRIMARY_EVIDENCE)]
    if len(evidenced) == 1:
        return evidenced[0]
    if evidenced:
        return max(evidenced, key=lambda b: (b.confidence, len(b.features or [])))
    if len(bedrooms) == 1:
        return bedrooms[0]
    # No explicit primary evidence across multiples → leave all secondary
    return None


def _names_for_space(
    space: SpaceInventoryItem,
    *,
    bedroom_count: int,
    primary_bedroom_id: str | None,
    study_count: int,
) -> tuple[str, str, str]:
    """Return (display_name, narration_name, room_role)."""
    space_type = (space.type or "Unknown").strip() or "Unknown"
    key = make_instance_id(space.type, space.instance)

    if space_type in ("Bedroom", "Guest Bedroom"):
        if primary_bedroom_id and key == primary_bedroom_id:
            return "Primary Bedroom", "Primary Bedroom", "primary"
        if _has_evidence(space, GUEST_EVIDENCE) and _has_bed(space):
            return "Guest Bedroom", "Guest Bedroom", "secondary"
        if bedroom_count <= 1:
            return "Bedroom", "Bedroom", "primary"
        # Multiple bedrooms, no master-suite evidence → do not guess 主卧/次卧.
        return "Bedroom", "Bedroom", "secondary"

    if space_type == "Study Room":
        if study_count > 1:
            return "Study Area", "Study Area", "secondary"
        return "Study Area", "Study Area", "secondary"

    defaults = _TYPE_DEFAULTS.get(space_type)
    if defaults:
        return defaults

    # Unknown / custom types: strip trailing digits, never speak instance numbers
    clean = re.sub(r"\s+\d+$", "", space_type).strip() or "Room"
    return clean, clean, "secondary"


def normalize_space_item(
    space: SpaceInventoryItem,
    *,
    bedroom_count: int,
    primary_bedroom_id: str | None,
    study_count: int,
) -> SpaceInventoryItem:
    """Fill instance_id + user-facing names on one inventory item."""
    space.type = (space.type or "Unknown").strip() or "Unknown"
    space.instance = max(int(space.instance or 1), 1)
    space.instance_id = make_instance_id(space.type, space.instance)
    display, narration, role = _names_for_space(
        space,
        bedroom_count=bedroom_count,
        primary_bedroom_id=primary_bedroom_id,
        study_count=study_count,
    )
    space.display_name = display
    space.narration_name = narration
    # Keep Verified Space Layer roles (primary / secondary / glimpse) when set.
    if (space.room_role or "") not in {"primary", "secondary", "glimpse"}:
        space.room_role = role
    return space


def normalize_segment_spaces(segments: list[VKBSegment]) -> list[VKBSegment]:
    """Normalize space names across a segment list in place."""
    unique = _collect_unique_spaces(list(segments or []))

    bedrooms = [
        s for s in unique if (s.type or "").strip() in ("Bedroom", "Guest Bedroom")
    ]
    studies = [s for s in unique if (s.type or "").strip() == "Study Room"]
    primary = _pick_primary_bedroom(bedrooms)
    primary_id = (
        make_instance_id(primary.type, primary.instance) if primary is not None else None
    )
    bedroom_count = len(bedrooms)
    study_count = len(studies)

    for seg in segments or []:
        spaces = list(seg.knowledge.spaces or [])
        for space in spaces:
            normalize_space_item(
                space,
                bedroom_count=bedroom_count,
                primary_bedroom_id=primary_id,
                study_count=study_count,
            )
        seg.knowledge.spaces = spaces

    logger.info(
        "Room naming normalized: bedrooms=%d primary=%s studies=%d spaces=%d",
        bedroom_count,
        primary_id or "-",
        study_count,
        len(unique),
    )
    return segments


def normalize_room_names(vkb: VisionKnowledgeBase) -> VisionKnowledgeBase:
    """Normalize all VKB space names in place. Idempotent."""
    normalize_segment_spaces(list(vkb.segments or []))
    return vkb


def narration_label(space: SpaceInventoryItem) -> str:
    """Script-facing label — never an instance id."""
    return (
        (space.narration_name or "").strip()
        or (space.display_name or "").strip()
        or (space.type or "").strip()
    )


def display_label(space: SpaceInventoryItem) -> str:
    """UI-facing label — never an instance id."""
    return (
        (space.display_name or "").strip()
        or (space.narration_name or "").strip()
        or (space.type or "").strip()
    )
