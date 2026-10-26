# GREYBOX

**Human × AI — 任せる、検証する、決断する。**

GREYBOX is a junior-engineer learning game about choosing the right boundary between AI delegation and human understanding, verification, and decision-making.

## Portable story source

- `story/stage01.json` — engine-independent story and choices
- `story/schema.json` — JSON Schema for the story format

The JSON story is the canonical source. Ren'Py is intended to be a runtime adapter, not the place where story content is hard-coded.

## Design principles

1. AI may do work; its completion claim is not proof of correctness.
2. Human verification should be proportional to risk.
3. The player is evaluated on quality, evidence, risk management, and efficiency—not on reading every line or blindly trusting the AI.
4. Story data must not execute embedded Python or arbitrary expressions.
5. Scene and choice IDs are stable identifiers; display text may change without breaking references.

## Story format v1

Scene types:
- `dialogue`: speaker, text, and next scene
- `choice`: prompt and choices; each choice can declare state effects and a next scene
- `event`: named event handled by the runtime adapter
- `ending`: terminal result

The schema validates structure. A separate semantic validator should check unique scene/choice IDs, valid speaker references, valid scene links, and reachable endings.

## Current scope

Stage 01: **The Unverified Patch**. The sample story is a design artifact; no Ren'Py runtime implementation or automated tests are included yet.


## Ren'Py runtime

The initial Ren'Py project files are in `game/`:

- `game/script.rpy` — game entry point
- `game/story_adapter.rpy` — JSON-driven dialogue, choices, effects, and scene-link checks
- `game/options.rpy` — project settings
- `game/story/stage01.json` — packaged runtime copy of the canonical `story/stage01.json`

When editing the story, update the canonical `story/stage01.json` and copy it to `game/story/stage01.json` so exported Ren'Py builds include the same content. This first runtime pass has not yet been launched in the Ren'Py SDK; run it locally to catch engine-version or UI issues.
