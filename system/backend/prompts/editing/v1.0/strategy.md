# Editing Strategy Agent - Strategy Prompt

Version: 1.0.0

## Task

Select cinematic editing strategies for each segment of the real estate video.

## Input

- Optimized timeline: {timeline}
- Vision analysis: {vision_json}

## Instructions

1. Review the timeline for each segment
2. Consider the adjustment strategy (slow_motion, freeze_frame, etc.)
3. Select the primary visual strategy for each segment
4. Plan transitions between segments
5. Explain why each strategy was chosen

## Strategy Selection Guidelines

- Slow motion: best for spacious rooms, luxury features
- Freeze frame: ideal for highlighting specific features
- Zoom: useful for drawing attention to details
- Callout: when a feature needs labeling
- Ken Burns: for segments that need extension with still frames
- Subtitle card: for price, square footage, or feature labels

## Output

For each segment, provide:
- strategy type
- parameters (zoom level, speed factor, etc.)
- reason for selection
- priority level
