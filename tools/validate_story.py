#!/usr/bin/env python3
"""Semantic validator for GREYBOX story JSON.

`story/schema.json` only checks structure. This checks the things that make a
story actually playable:

  * unique scene ids / choice ids
  * every `next` target exists
  * every `dialogue.speaker` is declared in `characters`
  * every `event.event` is declared in `events`
  * every `effects` key exists in `initial_state`
  * every scene is reachable from `start_scene`
  * no cycles (the runtime has no loop protection)
  * at least one reachable ending, and every path terminates in one
  * simulated final state per path (warns on negative time / budget)

Usage:
    python tools/validate_story.py
    python tools/validate_story.py --story story/stage01.json --verbose
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STORY = ROOT / "story" / "stage01.json"
SCHEMA_PATH = ROOT / "story" / "schema.json"

SCALARS = (bool, int, float, str)

errors: list[str] = []
warnings: list[str] = []


def check_schema(story: dict[str, Any], schema_path: Path = SCHEMA_PATH) -> list[str]:
    """Structural validation against story/schema.json.

    Skipped (with a warning) when jsonschema is not installed, so the validator
    still works with a bare Python install.
    """
    try:
        import jsonschema
    except ImportError:
        warn("jsonschema is not installed; skipping structural validation")
        return []

    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    messages: list[str] = []
    for failure in sorted(validator.iter_errors(story), key=lambda e: list(e.absolute_path)):
        location = "/".join(str(part) for part in failure.absolute_path) or "<root>"
        if failure.context:
            details = []
            for sub in failure.context:
                sub_location = "/".join(str(part) for part in sub.absolute_path)
                details.append(f"{sub_location}: {sub.message}" if sub_location else sub.message)
            message = "; ".join(dict.fromkeys(details))
        else:
            message = failure.message
        messages.append(f"{location}: {message}")
    return messages


def error(message: str) -> None:
    errors.append(message)


def warn(message: str) -> None:
    warnings.append(message)


def apply_effects(state: dict[str, Any], effects: dict[str, Any]) -> dict[str, Any]:
    """Mirror of greybox_apply_effects in game/story_adapter.rpy."""
    state = dict(state)
    for key, value in effects.items():
        if isinstance(value, bool):
            state[key] = value
        elif (
            isinstance(value, (int, float))
            and isinstance(state.get(key), (int, float))
            and not isinstance(state.get(key), bool)
        ):
            state[key] += value
        else:
            state[key] = value
    return state


def check_top_level(story: dict[str, Any]) -> None:
    required = [
        "schema_version",
        "story_id",
        "title",
        "language",
        "start_scene",
        "characters",
        "initial_state",
        "scenes",
    ]
    for key in required:
        if key not in story:
            error(f"missing top-level key: {key}")
    if story.get("schema_version") != "1.0":
        warn(f"unexpected schema_version: {story.get('schema_version')!r}")


def check_structure(
    story: dict[str, Any], scene_map: dict[str, dict[str, Any]]
) -> dict[str, list[str]]:
    """Returns the adjacency list used for reachability and cycle checks."""
    characters = story.get("characters", {})
    events = story.get("events", {})
    initial_state = story.get("initial_state", {})
    edges: dict[str, list[str]] = {}
    choice_ids: dict[str, str] = {}

    for scene in story["scenes"]:
        scene_id = scene["id"]
        scene_type = scene["type"]
        targets: list[str] = []

        if scene_type == "dialogue":
            if scene["speaker"] not in characters:
                error(f"scene '{scene_id}': unknown speaker '{scene['speaker']}'")
            targets = [scene["next"]]
        elif scene_type == "event":
            if scene["event"] not in events:
                error(f"scene '{scene_id}': unknown event '{scene['event']}'")
            targets = [scene["next"]]
        elif scene_type == "choice":
            if not scene["choices"]:
                error(f"scene '{scene_id}': choice scene has no choices")
            for choice in scene["choices"]:
                if choice["id"] in choice_ids:
                    error(
                        f"choice id '{choice['id']}' is used twice "
                        f"(scenes '{choice_ids[choice['id']]}' and '{scene_id}')"
                    )
                choice_ids[choice["id"]] = scene_id
                for key, value in choice.get("effects", {}).items():
                    if key not in initial_state:
                        error(
                            f"choice '{choice['id']}': effect key '{key}' "
                            f"is not defined in initial_state"
                        )
                    if not isinstance(value, SCALARS):
                        error(
                            f"choice '{choice['id']}': effect '{key}' must be a scalar "
                            f"(got {type(value).__name__})"
                        )
                targets.append(choice["next"])
        elif scene_type == "ending":
            if scene.get("outcome") not in ("success", "partial", "failure"):
                error(f"scene '{scene_id}': invalid outcome {scene.get('outcome')!r}")
        else:
            error(f"scene '{scene_id}': unsupported type '{scene_type}'")
            continue

        for target in targets:
            if target not in scene_map:
                error(f"scene '{scene_id}': next target '{target}' does not exist")

        edges[scene_id] = [t for t in targets if t in scene_map]

    for name, effects in events.items():
        for key, value in effects.items():
            if key not in initial_state:
                error(
                    f"event '{name}': effect key '{key}' is not defined in initial_state"
                )
            if not isinstance(value, SCALARS):
                error(
                    f"event '{name}': effect '{key}' must be a scalar "
                    f"(got {type(value).__name__})"
                )

    used_events = {s["event"] for s in story["scenes"] if s["type"] == "event"}
    for name in events:
        if name not in used_events:
            warn(f"event '{name}' is defined but never used")

    return edges


def check_reachability(
    story: dict[str, Any], scene_map: dict[str, dict[str, Any]], edges: dict[str, list[str]]
) -> set[str]:
    start = story["start_scene"]
    if start not in scene_map:
        error(f"start_scene '{start}' does not exist")
        return set()

    seen = {start}
    queue = [start]
    while queue:
        current = queue.pop()
        for target in edges.get(current, []):
            if target not in seen:
                seen.add(target)
                queue.append(target)

    for scene_id in scene_map:
        if scene_id not in seen:
            error(f"scene '{scene_id}' is unreachable from start_scene '{start}'")

    return seen


def check_cycles(edges: dict[str, list[str]]) -> None:
    WHITE, GREY, BLACK = 0, 1, 2
    color = dict.fromkeys(edges, WHITE)
    stack: list[str] = []

    def visit(node: str) -> None:
        color[node] = GREY
        stack.append(node)
        for target in edges.get(node, []):
            if color.get(target, BLACK) == GREY:
                cycle = " -> ".join(stack[stack.index(target):] + [target])
                error(f"cycle detected: {cycle}")
            elif color.get(target, BLACK) == WHITE:
                visit(target)
        stack.pop()
        color[node] = BLACK

    for node in edges:
        if color[node] == WHITE:
            visit(node)


def enumerate_paths(
    story: dict[str, Any], scene_map: dict[str, dict[str, Any]]
) -> list[tuple[list[str], dict[str, Any]]]:
    """Walks the story graph, returning (path, final_state) for every playthrough."""
    results: list[tuple[list[str], dict[str, Any]]] = []

    def walk(
        scene_id: str, state: dict[str, Any], path: list[str], seen: frozenset[str]
    ) -> None:
        if scene_id in seen or len(path) > 100:
            return
        scene = scene_map[scene_id]
        scene_type = scene["type"]
        path = path + [scene_id]

        if scene_type == "dialogue":
            walk(scene["next"], state, path, seen | {scene_id})
        elif scene_type == "event":
            state = apply_effects(state, story.get("events", {}).get(scene["event"], {}))
            walk(scene["next"], state, path, seen | {scene_id})
        elif scene_type == "choice":
            for choice in scene["choices"]:
                walk(
                    choice["next"],
                    apply_effects(state, choice.get("effects", {})),
                    path + [f"[{choice['id']}]"],
                    seen | {scene_id},
                )
        elif scene_type == "ending":
            results.append((path, state))

    walk(story["start_scene"], dict(story.get("initial_state", {})), [], frozenset())
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--story", type=Path, default=DEFAULT_STORY)
    parser.add_argument("--verbose", action="store_true", help="print every playthrough")
    parser.add_argument(
        "--allow-cycles", action="store_true", help="downgrade cycle errors to warnings"
    )
    args = parser.parse_args()

    if not args.story.is_file():
        print(f"error: story not found: {args.story}", file=sys.stderr)
        return 1

    try:
        story = json.loads(args.story.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"error: invalid JSON in {args.story}: {exc}", file=sys.stderr)
        return 1

    check_top_level(story)
    if errors:
        for message in errors:
            print(f"ERROR  {message}", file=sys.stderr)
        return 1

    schema_messages = check_schema(story)
    if schema_messages:
        for message in schema_messages:
            print(f"ERROR  schema: {message}", file=sys.stderr)
        print(
            f"\nFAILED: {len(schema_messages)} schema error(s) in {args.story}",
            file=sys.stderr,
        )
        return 1

    scenes = story["scenes"]
    scene_ids = [scene["id"] for scene in scenes]
    duplicates = {sid for sid in scene_ids if scene_ids.count(sid) > 1}
    for sid in sorted(duplicates):
        error(f"duplicate scene id: {sid}")

    scene_map = {scene["id"]: scene for scene in scenes}
    edges = check_structure(story, scene_map)
    check_reachability(story, scene_map, edges)
    check_cycles(edges)

    paths = enumerate_paths(story, scene_map) if not errors else []
    reachable_endings = {path[-1] for path, _ in paths}

    if not errors:
        if not reachable_endings:
            error("no reachable ending")
        for ending_id in reachable_endings:
            outcome = scene_map[ending_id].get("outcome")
            if outcome not in ("success", "partial", "failure"):
                error(f"ending '{ending_id}' has an invalid outcome")

    for path, state in paths:
        if state.get("time", 0) < 0:
            warn(f"path ending in '{path[-1]}' finishes with negative time: {state.get('time')}")
        if state.get("budget", 0) < 0:
            warn(
                f"path ending in '{path[-1]}' finishes with negative budget: {state.get('budget')}"
            )
        if state.get("risk", 0) < 0:
            warn(
                f"path ending in '{path[-1]}' finishes with negative risk: {state.get('risk')}"
            )

    for message in warnings:
        print(f"WARN   {message}", file=sys.stderr)
    for message in errors:
        print(f"ERROR  {message}", file=sys.stderr)

    if args.verbose and paths:
        print("\nPlaythroughs:")
        for path, state in paths:
            print(
                "  {}\n    time={} budget={} quality={} risk={} verified={}".format(
                    " > ".join(path),
                    state.get("time"),
                    state.get("budget"),
                    state.get("quality"),
                    state.get("risk"),
                    state.get("verified"),
                )
            )

    if errors:
        print(
            f"\nFAILED: {len(errors)} error(s), {len(warnings)} warning(s) in {args.story}",
            file=sys.stderr,
        )
        return 1

    print(
        f"OK: {len(scenes)} scenes, {len(paths)} playthrough(s), "
        f"{len(reachable_endings)} reachable ending(s), {len(warnings)} warning(s)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
