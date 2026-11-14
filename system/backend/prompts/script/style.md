# Script Agent - Style Controller (Reference Document)

Version: 1.0.0

This module is **rule-based only**. It is NOT sent to any LLM. Style
Controller controls language *distribution*, it never generates content.

## Style -> Effect Mapping

| Style keyword | Effect |
|---|---|
| warm | emotional words retained; clinical/cold/sterile words stripped |
| luxury / premium | premium vocabulary retained; basic/plain/cheap words stripped |
| minimal / modern | short sentence-length band enforced |
| cinematic / premium_feel tag | dynamic energy (paired with Scene Narrator's verb choice) |

## Sentence Length Bands (word count)

| Band | Min | Max |
|---|---|---|
| short | 5 | 10 |
| medium | 9 | 18 |
| long | 16 | 28 |

## Processing

1. `derive_style()` maps Director Intent (`emotional_tone`, `intent_tags`) to a `StyleConfig`.
2. `apply()` strips tone-inappropriate banned words, then hard-caps sentence length to the style's band.

Duration-based fitting against actual scene timing is intentionally
**not** handled here — that belongs to the Timeline Alignment Engine
(Module 4), which reasons about seconds, not vocabulary.
