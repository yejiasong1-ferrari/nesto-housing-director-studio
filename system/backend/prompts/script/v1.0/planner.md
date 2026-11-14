# Script Agent - Narrative Planner (Reference Document)

Version: 1.0.0

This module is **rule-based only**. It is NOT sent to any LLM. This
document exists purely to make the deterministic logic explainable and
auditable, per the "Prompt Management" section of `cursor.md`.

## Why rule-based?

The Planner Agent already performs LLM-informed reasoning to decide:

- attention roles (HERO / SUPPORT / TRANSITION) via contrastive normalization
- narrative function and emotion per scene
- editorial hierarchy

Re-running this reasoning inside the Script Agent would duplicate cognition
and violate the "Perceive/Plan Once, Reuse Everywhere" principle. Instead,
the Narrative Planner module simply reformats those existing decisions
into a story-arc label per scene.

## Deterministic Rule

For scenes in original video order `[0 .. n-1]`:

```
if index == 0:              arc = "hook"
elif index == n - 1:        arc = "close"
elif role == "HERO":        arc = "highlight"
else:                       arc = "explore"
```

`scene_order` is always identical to the Vision Knowledge Base's original
segment order — Script Agent never reorders scenes.
