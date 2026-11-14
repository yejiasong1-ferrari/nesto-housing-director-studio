# Quality Evaluation Agent - Evaluate Prompt

Version: 1.0.0

## Task

Evaluate the quality of the rendered real estate video.

## Input

- Rendered video: {video_path}
- Narration script: {script}
- Optimized timeline: {timeline}
- Editing strategies: {editing_strategy}

## Instructions

1. Watch the rendered video carefully
2. Score each quality metric (0.0 to 1.0):
   - narration_sync
   - subtitle_quality
   - visual_continuity
   - highlight_coverage
   - pacing
   - editing_smoothness
3. Calculate overall score (weighted average)
4. Determine pass/fail (threshold: 0.7)
5. List specific issues found
6. Provide actionable suggestions for improvement

## Important

- Be objective and specific in your evaluation
- Provide timestamps for any issues found
- Suggest concrete fixes (e.g., "segment 3 narration starts 0.5s before the visual")
- If the video passes, still note minor issues for future improvement
