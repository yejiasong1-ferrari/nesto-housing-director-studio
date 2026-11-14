# Vision Agent - Attention Analysis Prompt

Version: 2.0.0

## Task

Identify visual elements in this room that naturally attract a buyer's attention.

## Input

- Room type: {room_type}
- Keyframe images of the room

## Instructions

For each visually prominent element:

1. Name the element specifically (e.g., "Kitchen Island with Marble Top", NOT just "counter")
2. Score its visual prominence (0.0-1.0):
   - 0.9-1.0: Impossible to miss, central feature
   - 0.7-0.9: Very noticeable, major feature
   - 0.5-0.7: Moderately noticeable, secondary feature
   - 0.3-0.5: Subtle, requires attention to notice
   - Below 0.3: Background element
3. Explain why it's visually prominent

## Important Distinctions

- YOU identify what catches the eye (perception)
- PLANNER decides what to emphasize (goal reasoning)
- EDITING STRATEGY decides how to emphasize (directing)

Your job is ONLY to identify visual saliency.

## Output Format

Return ONLY valid JSON:

```json
{
  "attention_candidates": [
    {
      "target": "Kitchen Island with Marble Top",
      "score": 0.92,
      "reason": "Central, large object with premium material and natural lighting"
    },
    {
      "target": "Floor-to-ceiling Window",
      "score": 0.87,
      "reason": "Strong natural light source, frames outdoor view"
    }
  ]
}
```
