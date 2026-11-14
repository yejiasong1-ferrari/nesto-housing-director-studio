# Vision Agent - Room Analysis Prompt

Version: 2.0.0

## Task

Analyze the provided keyframe images of a room from a real estate walkthrough video.

## Input

- Representative keyframe images (2-4 images showing different angles)
- Attention hint: {attention_hint}

## Instructions

1. Identify the room type (be specific: "Kitchen" not just "Room")
2. Assess the decoration style
3. Evaluate lighting quality
4. Describe the spatial layout
5. List all visible furniture
6. List all visible appliances
7. Identify selling points (features that would appeal to buyers)
8. Describe camera motion through the space
9. Provide your confidence level

Attention hint guidance:
- If a hint is provided (e.g., "focus on kitchen"), describe that area in MORE detail
- The hint does NOT change WHAT the room is (kitchen is kitchen)
- It only affects the LEVEL of detail in descriptions

## Output Format

Return ONLY valid JSON:

```json
{
  "room_type": "Kitchen",
  "confidence": 0.95,
  "style": "Modern",
  "layout": "Open",
  "lighting": "Excellent",
  "selling_points": [
    "Large Kitchen Island with Quartz Countertop",
    "Bosch Built-in Oven",
    "Floor-to-ceiling Window"
  ],
  "furniture": ["Kitchen Island", "Bar Stools", "Dining Table"],
  "appliances": ["Bosch Oven", "Refrigerator", "Dishwasher"],
  "camera": {
    "motion": "Forward",
    "speed": "Slow"
  },
  "notes": "Open concept kitchen flowing into dining area"
}
```

## Critical Rules

- Be SPECIFIC about selling points (not "nice counter" but "Quartz Countertop")
- Be HONEST about confidence (if unsure, rate lower)
- Be OBJECTIVE (no marketing language, no subjective praise)
- Return ONLY JSON (no markdown, no explanation)
