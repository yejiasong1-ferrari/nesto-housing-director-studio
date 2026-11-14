"""Director emphasis parsing + presence gating (no fabrication)."""

from __future__ import annotations

from backend.workflows.emphasis import (
    has_emphasis_request,
    matched_facts,
    parse_emphasis_targets,
    present_targets,
    target_present,
)


def test_parse_chinese_object_request() -> None:
    assert parse_emphasis_targets("多介绍床") == ["bed"]
    assert "sofa" in parse_emphasis_targets("重点突出沙发和电视")
    assert "tv" in parse_emphasis_targets("重点突出沙发和电视")


def test_parse_english_object_request() -> None:
    targets = parse_emphasis_targets("please highlight the bed and the window")
    assert "bed" in targets
    assert "window" in targets


def test_generic_brief_has_no_object_targets() -> None:
    # Generic coverage brief should not force any specific object emphasis
    assert parse_emphasis_targets("介绍每个空间和采光") != ["bed"]


def test_emphasis_marker_detection() -> None:
    assert has_emphasis_request("多介绍床")
    assert has_emphasis_request("highlight the kitchen island")
    assert not has_emphasis_request("just a normal tour")


def test_matched_facts_only_when_present() -> None:
    knowledge_with_bed = {
        "room_type": "Bedroom",
        "selling_points": ["Spacious layout"],
        "furniture": ["King bed", "Nightstand"],
        "appliances": [],
    }
    knowledge_without_bed = {
        "room_type": "Kitchen",
        "selling_points": ["Kitchen island"],
        "furniture": [],
        "appliances": ["Refrigerator"],
    }
    assert matched_facts(["bed"], knowledge_with_bed) == ["King bed"]
    # No fabrication: bed absent from kitchen facts → nothing promoted
    assert matched_facts(["bed"], knowledge_without_bed) == []


def test_target_present_checks_room_and_facts() -> None:
    bedroom = {"room_type": "Bedroom", "selling_points": [], "furniture": [], "appliances": []}
    assert target_present("bedroom", bedroom)
    assert present_targets(["bed", "sofa"], {
        "room_type": "Living Room",
        "selling_points": [],
        "furniture": ["Sectional sofa"],
        "appliances": [],
    }) == ["sofa"]
