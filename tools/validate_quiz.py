#!/usr/bin/env python3
"""Validate a GREYBOX quiz file against the story it belongs to.

Quiz content lives in its own file (`story/<stage>.quiz.json`) and references
story scenes by id, so story text and quiz text never mix. This checks that the
two stay consistent:

  * the quiz conforms to `story/quiz.schema.json` (when jsonschema is installed)
  * `quiz.story_id` equals the story's `story_id`
  * every `question.scene_id` exists in the story
  * question ids are unique; choice ids are unique within a question
  * every `answer` points at one of that question's choices

Usage:
    python tools/validate_quiz.py
    python tools/validate_quiz.py --story story/stage01.json --quiz story/quiz.stage01.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STORY = ROOT / "story" / "stage01.json"
DEFAULT_QUIZ = ROOT / "story" / "quiz.stage01.json"
SCHEMA = ROOT / "story" / "quiz.schema.json"

errors: list[str] = []
warnings: list[str] = []


def error(message: str) -> None:
    errors.append(message)


def warn(message: str) -> None:
    warnings.append(message)


def schema_errors(document: Any, schema_path: Path) -> list[str]:
    """Structural errors from JSON Schema, if jsonschema is available."""
    try:
        import jsonschema
    except ImportError:
        warn("jsonschema is not installed; skipping structural validation")
        return []

    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    messages: list[str] = []
    for failure in sorted(validator.iter_errors(document), key=lambda e: list(e.absolute_path)):
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


def check_quiz(quiz: dict[str, Any], story: dict[str, Any]) -> None:
    story_scene_ids = {scene["id"] for scene in story.get("scenes", [])}
    story_id = story.get("story_id")

    if quiz.get("story_id") != story_id:
        error(
            f"quiz.story_id is '{quiz.get('story_id')}' but the story is '{story_id}'"
        )

    if quiz.get("language") and story.get("language") and quiz["language"] != story["language"]:
        warn(
            f"quiz language '{quiz['language']}' differs from story language "
            f"'{story['language']}'"
        )

    seen_questions: dict[str, int] = {}
    for index, question in enumerate(quiz.get("questions", [])):
        question_id = question.get("id", f"<question {index}>")
        if question_id in seen_questions:
            error(f"duplicate question id '{question_id}'")
        seen_questions[question_id] = index

        scene_id = question.get("scene_id")
        if scene_id not in story_scene_ids:
            error(f"question '{question_id}': scene_id '{scene_id}' is not in the story")

        choice_ids = [choice.get("id") for choice in question.get("choices", [])]
        if len(choice_ids) != len(set(choice_ids)):
            error(f"question '{question_id}': duplicate choice id")

        answer = question.get("answer")
        if answer not in choice_ids:
            error(
                f"question '{question_id}': answer '{answer}' is not one of its choices "
                f"({', '.join(str(c) for c in choice_ids)})"
            )

        texts = [choice.get("text") for choice in question.get("choices", [])]
        if len(texts) != len(set(texts)):
            warn(f"question '{question_id}': two choices have identical text")

        if not question.get("explanation"):
            warn(f"question '{question_id}': no explanation; the player learns nothing on a miss")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--story", type=Path, default=DEFAULT_STORY)
    parser.add_argument("--quiz", type=Path, default=DEFAULT_QUIZ)
    args = parser.parse_args()

    for path in (args.story, args.quiz):
        if not path.is_file():
            print(f"error: file not found: {path}", file=sys.stderr)
            return 1

    try:
        story = json.loads(args.story.read_text(encoding="utf-8"))
        quiz = json.loads(args.quiz.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"error: invalid JSON: {exc}", file=sys.stderr)
        return 1

    for message in schema_errors(quiz, SCHEMA):
        error(f"schema: {message}")

    check_quiz(quiz, story)

    for message in warnings:
        print(f"WARN   {message}", file=sys.stderr)
    for message in errors:
        print(f"ERROR  {message}", file=sys.stderr)

    if errors:
        print(
            f"\nFAILED: {len(errors)} error(s), {len(warnings)} warning(s) in {args.quiz}",
            file=sys.stderr,
        )
        return 1

    print(
        f"OK: {len(quiz['questions'])} question(s) linked to {args.story.name}, "
        f"{len(warnings)} warning(s)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
