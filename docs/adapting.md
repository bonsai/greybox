# Adapting incoming content (story + quiz)

Story text and quiz text arrive **separately** and stay separate in the repo.
The adapter (a human or the `greybox-adapter` agent) converts each draft into
the repo's JSON format and proves the two still line up.

```
inbox/story/<stage>.md  ──┐
                          ├─►  story/<stage>.json        (story schema v1)
inbox/quiz/<stage>.md   ──┘    story/<stage>.quiz.json   (quiz schema v1)
                                     │
                                     ├─► tools/sync_story.py  → game/story/
                                     └─► tools/validate_story.py + validate_quiz.py
```

`inbox/` is a scratch area (git-ignored). Only the generated JSON is committed.

## Why they are separate

- Story JSON must stay engine-independent and free of quiz logic.
- Quizzes are linked to scenes by `scene_id`, so a question can be rewritten or
  removed without touching the story.
- The runtime may show a quiz after a scene, before an ending, or not at all;
  that decision belongs to the runtime, not the data.

The only shared keys are `story_id` (file level) and `scene_id` (question level).

## Story draft → `story/<stage>.json`

Required from the draft, without inventing content:

| Field | Rule |
| --- | --- |
| `story_id` | `greybox.<stage>` |
| `language` | matches the draft language |
| `characters` | one entry per speaker; `role` is a short snake_case label |
| `initial_state` | every key that any `effects` block touches |
| `scenes` | snake_case `id`; `dialogue` / `choice` / `event` / `ending` |
| `events` | data-only effects; event scenes reference these names |

Rules:

1. **No new content.** Do not add choices, endings, events or jokes that are not
   in the draft. If the draft is ambiguous, ask — do not fill the gap.
2. **No code.** JSON never contains expressions, Python, `eval`, or `if`.
   Conditional behaviour is expressed as choices and `events` effects.
3. Numeric effects are deltas, booleans/strings replace the value, and every
   `effects` key must exist in `initial_state`.
4. Every non-ending scene has `next`; every path terminates in an `ending`.
   No cycles.
5. Display text may be edited for clarity; `id`, `scene_id`, `story_id` may not
   change once committed.

## Quiz draft → `story/<stage>.quiz.json`

| Field | Rule |
| --- | --- |
| `quiz_id` | `greybox.<stage>.quiz` |
| `story_id` | must equal the story's `story_id` |
| `questions[].scene_id` | an existing scene id in that story |
| `questions[].answer` | one of that question's `choices[].id` |
| `explanation` | required; say *why*, not just "correct" |

Rules:

1. One question, one idea. Put the scene that teaches it in `scene_id`.
2. Exactly one choice is correct. Distractors must be plausible, not absurd.
3. Options are self-contained (no "all of the above", no "both A and B").
4. Correct answer ids are never `"a"`/`"b"` only — use meaningful ids such as
   `test_and_criteria`.
5. Quizzes never appear inside story JSON.

## Verification (must pass before the work is reported as done)

```bash
python tools/sync_story.py                 # story/ -> game/story/
python tools/validate_story.py --verbose   # schema + semantics + every path
python tools/validate_quiz.py              # quiz <-> story cross-check
python -m unittest discover -s tools -p "test_*.py"
```

Ren'Py projects can additionally run `renpy.exe <project> compile` and
`renpy.exe <project> lint`; both must exit 0.

## When to stop and ask

- The draft has a branch with no ending.
- Two scenes would need the same id.
- A quiz question has no matching scene.
- The draft wants a mechanic that the schema cannot express (loops, timers,
  per-character affection counters are fine only if they live in
  `initial_state`).
- Faithfully adapting the draft would fail validation and the fix is not
  mechanical.
