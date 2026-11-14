# Voice Style Selection Guide

Map director intent to voice personality presets.

## Luxury listing

- tone: calm, premium, confident
- speed: slow to normal
- voice: mature, polished

## Family apartment

- tone: warm, friendly, energetic
- speed: normal
- voice: approachable, inviting

## Rental listing

- tone: clear, informative
- speed: slightly faster
- voice: neutral, efficient

## Rhythm by narrative arc

| Arc stage  | Speed   | Pause after |
|------------|---------|-------------|
| hook       | slow    | 0.5–0.8s    |
| explore    | normal  | 0.3–0.5s    |
| highlight  | normal  | 0.4–0.6s    |
| close      | slow    | 0.8–1.2s    |

## Duration prediction

Estimated duration = pause_before + (words / speech_rate) + pause_after

When `estimated_duration > scene_duration`, flag for Timeline Optimization.
