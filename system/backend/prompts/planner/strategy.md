# Planner Agent - Timeline Strategy Prompt

Version: 1.0.0

Select editing strategies for each segment. Do NOT adjust timestamps or reorder.

## Segments

{segments_json}

## Allowed Strategies

Choose from ONLY these abstract strategies:
- slow_push_in
- zoom
- subtitle_callout
- object_highlight
- standard_pace
- fast_pace
- transition_fade
- ken_burns
- freeze_frame

## Rules

- hero_segment (importance >= 0.85): prefer slow_push_in, zoom, subtitle_callout
- support_segment: prefer zoom, subtitle_callout
- transition_segment: prefer standard_pace, transition_fade
- NEVER reorder segments
- NEVER adjust start/end times

## Output

Return STRICT JSON only:

```json
{{
  "timeline_plan": [
    {{
      "segment_id": "seg_02",
      "editing_strategy": ["slow_push_in", "zoom", "subtitle_callout"]
    }}
  ]
}}
```
