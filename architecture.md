# AI Director Agent

## System Architecture

Version: 1.0

---

# 1. Introduction

AI Director is an autonomous cognitive multi-agent system designed for automatic real estate video production.

Unlike traditional AI video editors, AI Director does not directly transform a video into an edited result.

Instead, it decomposes the production process into multiple specialized cognitive agents that collaboratively understand the video, plan the narrative, optimize the timeline, determine editing strategies, and produce a final professional-quality real estate presentation.

The objective is to imitate how an experienced real estate director thinks rather than how a traditional editing software operates.

---

# 2. Design Philosophy

The architecture follows three fundamental principles.

## Principle 1

Separate Cognition from Execution.

Large Language Models perform reasoning.

Traditional software performs deterministic execution.

Reasoning includes

- understanding
- planning
- decision making
- evaluation

Execution includes

- rendering
- clipping
- subtitle generation
- synchronization
- exporting

---

## Principle 2

Every agent has exactly one cognitive responsibility.

No agent should perform multiple unrelated tasks.

---

## Principle 3

All agents communicate through a shared project state.

No direct dependency exists between agents.

This allows

- modularity
- explainability
- scalability
- maintainability

---

# 3. High-Level Architecture

```

User

│

├── Walkthrough Video

├── Prompt

└── Property Metadata

↓

Shared Project State

↓

Vision Agent

↓

Content Planner (Planner Agent)

↓

Script Agent              ← LLM required

↓

Timeline Agent (Pass 1)   ← estimated durations, no Voice yet
  │
  ├─ FLAG_REWRITE segments?
  │     ↓  YES
  │   ScriptAgent.rewrite_for_timeline()   [Rule, deterministic]
  │     ↓
  │   Timeline Agent (Pass 2)   ← re-evaluate rewritten narration
  │     ↓  (loop max 2 iterations)
  └─────┘

↓ [Timeline approved]

Voice Agent               ← only AFTER timeline approval

↓

Voice Execution Service   ← TTS synthesis

↓

Timeline Agent (Final)    ← actual measured audio durations

↓

Editing Strategy Agent

↓

Rendering Agent

↓

Quality Evaluation Agent

↓

Feedback Router (once)

↓

Final Rendering

↓

Final Video
```

Note: Evaluation appears exactly once. Infinite Render↔Evaluate loops are forbidden.

The architecture consists of three logical layers.

```

Perception Layer

↓

Reasoning Layer

↓

Execution Layer

```

---

# 4. System Layers

## 4.1 Perception Layer

Purpose

Transform raw videos into structured knowledge.

Primary Agent

Vision Agent

Responsibilities

- Room segmentation
- Timestamp localization
- Object recognition
- Visual attribute extraction
- Camera motion analysis
- Attention estimation

Input

Video

Output

Vision JSON

Example

```json
{
  "segments": [],
  "objects": [],
  "camera": {},
  "attributes": {},
  "attention": {}
}
```

The perception layer never generates narration or editing plans.

Its only objective is understanding.

---

## 4.2 Reasoning Layer

Purpose

Transform structured knowledge into creative decisions.

Agents

Content Planner

Script Agent

Voice Agent

Timeline Optimization Agent

Editing Strategy Agent

Quality Evaluation Agent

Unlike traditional pipelines, every reasoning module performs a different cognitive function.

Each agent focuses on one decision.

### Content Planner

Answers

What should be presented?

Produces

Importance

Focus

Target duration

---

### Script Agent

Answers

How should the property be described?

Produces

Narration.

---

### Voice Agent

Answers

How long is the actual narration?

Produces

Audio

Duration

Timestamp

---

### Timeline Optimization Agent

Core Innovation

Purpose

Align

Video Timeline

and

Audio Timeline.

Instead of immediately rendering videos, this module first reasons about timeline consistency.

Typical reasoning process

Audio longer than video?

↓

Is this segment important?

↓

Can slow motion solve the problem?

↓

Can freeze frame help?

↓

Need zoom?

↓

Need rewrite?

The output is an optimized timeline plan.

---

### Editing Strategy Agent

Core Innovation

Purpose

Transform Timeline narrative structure into professional director-level
visual expression plans.

Instead of editing videos directly, this module determines

how each segment should be visually expressed.

Architecture

- CinematicReasoner (LLM): visual goal, focus order, style hints
- Rule planners: visual / pacing / transition / subtitle / audio
- ConstraintValidator: reject illegal walkthrough operations

Possible strategies

- Slow Zoom / Slow Motion
- Freeze Frame
- Zoom
- Crop
- Ken Burns
- Soft Pan / Dissolve / Fade transitions
- Subtitle presentation
- Audio layer design (not music generation)

Boundaries

- MUST NOT change timestamps, merge/delete segments, or rewrite narration
- MUST NOT render media

This module outputs abstract editing strategies instead of executable rendering commands.

---

### Quality Evaluation Agent

Purpose

Final quality controller — **one** evaluation pass after draft render.

Compares

- Timeline
- Script
- Voice
- Editing Strategy
- Render metadata / final video

Produces

- weighted scores (AV 40% / timeline 20% / cinematic 15% / subtitle 15% / technical 10%)
- issue list
- single `priority_fixes` feedback package

Then

Feedback Router applies fixes once → Final Rendering → Final Video.

Evaluation Agent does **not** run again (no infinite self-reflection loop).

This mirrors professional production:

Draft Cut → Director Review → Final Cut.

---

## 4.3 Execution Layer

Purpose

Execute deterministic media operations.

Rendering Agent is the only execution agent.

Responsibilities

- video clipping
- timeline execution
- subtitle rendering
- audio synchronization
- fixed BGM underlay mix (`AudioMixer` + `audio_config`)
- transition rendering
- final exporting

Recommended tools

- FFmpeg
- MoviePy
- OpenCV

Rendering never performs reasoning.

### Continuous walkthrough execution (v2.2+)

For one-shot tours, Rendering uses `preserve_full_span=true`:

- Extract each timeline `[video_start, video_end]` fully
- Never `with_duration()` shorten below the extracted span
- Within a space, fill narration overrun with **continuous slow-motion**
  (footage keeps moving — do not freeze/pause to wait for audio)
- Force cut concatenation (no crossfade overlap that discards frames)
- Output canvas follows source orientation (landscape 1920×1080 /
  portrait 1080×1920) with letterbox/pillarbox — never stretch

Timeline still owns time structure; Rendering only executes without inventing cuts.

### Audio–video coupling (v3)

Rendering couples the video clock to the narration clock so audio and picture
stay in sync (deterministic execution):

- Predict each scene's narration start `max(video_cursor + offset, narr_guard)`.
- Stretch the visual window to `(+ audio + tail)` so the next scene's video
  never starts before the current narration ends, and narration never starts
  before its own scene is on screen.
- Fill extra time with a **single** slow-motion remap to the full window
  (no freeze remainder). Timeline should FLAG_REWRITE when stretch would
  drop below ~0.50× so playback stays smooth.

---

# 5. Shared Project State

The entire workflow revolves around a centralized Project State.

Every agent

reads

updates

its own state.

Example

```json
{
  "user_goal": {},
  "video_metadata": {},
  "audio_config": {
    "background_music": {
      "enabled": true,
      "path": "storage/audio/bgm/default_bgm.mp3",
      "volume_db": -25,
      "loop": true,
      "fade_in": 2,
      "fade_out": 3
    }
  },
  "vision": {},
  "planning": {},
  "script": {},
  "voice": {},
  "timeline": {},
  "editing": {},
  "render": {},
  "evaluation": {}
}
```

`audio_config` is workflow config (like resolution/fps), not an Agent decision.
V1 mixes one fixed BGM under narration inside Rendering (`AudioMixer`).

Advantages

- loose coupling
- reproducibility
- traceability
- debugging
- future memory extension

---

# 6. Data Flow

The system follows the following data flow.

```

Raw Video

↓

Vision JSON

↓

Content Plan

↓

Narration

↓

Voice

↓

Timeline

↓

Editing Strategy

↓

Rendering

↓

Evaluation

↓

Feedback

↓

Timeline

```

Every stage consumes structured information and produces new structured knowledge.

No module should directly manipulate outputs from unrelated modules.

---

# 7. Timeline Optimization

Timeline Optimization is the first feedback mechanism in the system.

Traditional workflow

```

Video

↓

Script

↓

Render

```

AI Director

```

Video

↓

Script

↓

Voice

↓

Timeline Optimization

↓

Editing Strategy

↓

Rendering

```

Timeline Optimization aligns visual duration with narration duration.

Instead of immediately shortening narration, the system first explores multiple cinematic strategies.

Examples

- Slow Motion
- Freeze Frame
- Zoom
- Insert Still Image
- Subtitle Card
- Rewrite Narration

This significantly improves video quality while preserving important selling points.

---

# 8. Editing Strategy

Editing Strategy represents cinematic decisions rather than rendering commands.

Example

```json
{
  "strategies": [
    "freeze_frame",
    "zoom",
    "callout"
  ]
}
```

Rendering translates these abstract strategies into executable operations.

This abstraction allows the architecture to evolve without changing rendering logic.

---

# 9. Closed-loop Workflow

The workflow is not linear.

Instead, it forms a cognitive feedback loop.

```

Vision

↓

Planning

↓

Generation

↓

Optimization

↓

Rendering

↓

Evaluation

↓

Replanning

```

This enables continuous refinement before producing the final video.

---

# 10. Future Extensions

The architecture is designed to support future capabilities.

Examples

- Multi-property editing
- Personalized editing styles
- User memory
- Reinforcement Learning
- Automatic thumbnail generation
- Multi-platform optimization
- Multi-language narration
- Interactive editing

These extensions should be implemented without changing the existing cognitive architecture.

---

# 11. Summary

AI Director is not a traditional video editing pipeline.

It is a cognitive multi-agent architecture composed of specialized reasoning modules.

The architecture separates perception, reasoning, execution, and evaluation into independent agents connected through a shared project state.

This design enables modularity, explainability, scalability, and autonomous decision making, allowing the system to gradually evolve from rule-based editing into an intelligent AI Director capable of producing professional real estate videos.