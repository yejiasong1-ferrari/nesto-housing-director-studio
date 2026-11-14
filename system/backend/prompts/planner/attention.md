# Planner Agent - Attention Allocator Prompt

Version: 1.0.0

Given director intent and vision segment information, assign initial intent-match attention scores.

## Director Intent

{intent_json}

## Vision Segments

{segments_json}

## Instructions

For EACH segment, assign an attention_score (0.0 to 1.0) reflecting how well this segment matches the user's intent.

Consider:
- Room type relevance to intent_tags
- Selling points alignment
- Lighting and style match to emotional_tone
- Target audience preferences

Do NOT reorder segments. Do NOT modify timestamps.

## Output

Return STRICT JSON array only:

```json
{{
  "attention_scores": [
    {{
      "segment_id": "seg_02",
      "attention_score": 0.92,
      "reason": ["kitchen_match", "lighting_match"]
    }}
  ]
}}
```
