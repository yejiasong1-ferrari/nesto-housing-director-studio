# Planner Agent - Segment Reasoner Prompt

Version: 1.0.0

Convert attention scores into cinematic meaning. Do NOT create narration or reorder timeline.

## Director Intent

{intent_json}

## Segments with Attention

{segments_json}

## Instructions

For each segment, determine:
- role: "hero_segment" (high attention), "support_segment" (medium), or "transition_segment" (low)
- focus_points: visual elements to emphasize (from selling points, NOT invented)
- narration_weight: 0.0 to 1.0 (how much narration time this segment deserves)

Do NOT generate marketing copy. Do NOT suggest editing strategies.

## Output

Return STRICT JSON only:

```json
{{
  "segment_reasoning": [
    {{
      "segment_id": "seg_02",
      "role": "hero_segment",
      "focus_points": ["kitchen island", "natural light", "open layout"],
      "narration_weight": 0.9
    }}
  ]
}}
```
