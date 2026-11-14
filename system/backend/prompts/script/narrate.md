# Script Agent - Narrate Prompt

Version: 1.0.0

## Task

Write narration for a real estate video based on the vision analysis and content plan.

## Input

- Vision analysis: {vision_json}
- Content plan: {content_plan}
- Property metadata: {property_metadata}
- User prompt: {user_prompt}

## Instructions

1. Review the content plan for segment priorities and focus points
2. For each segment, write narration that:
   - Introduces the room naturally
   - Highlights key features and selling points
   - Maintains target duration (approximately 150 words/minute)
   - Flows naturally from the previous segment
3. Write an intro that hooks the viewer
4. Write an outro with a call-to-action

## Tone

Use the tone specified in the content plan. Default: professional and warm.

## Important

- Do not describe things not visible in the video
- Do not invent features or dimensions not provided
- Keep narration timing within target durations
- Emphasize words that should receive vocal emphasis
