#!/usr/bin/env python3
"""Tests for tools/validate_quiz.py.

Each test copies the canonical quiz, breaks exactly one link, and asserts that
the validator exits non-zero.

    python -m unittest discover -s tools -p "test_*.py"
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VALIDATOR = ROOT / "tools" / "validate_quiz.py"
STORY = ROOT / "story" / "stage01.json"
QUIZ = ROOT / "story" / "quiz.stage01.json"


def run_validator(quiz: dict) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "quiz.json"
        path.write_text(json.dumps(quiz, ensure_ascii=False, indent=2), encoding="utf-8")
        return subprocess.run(
            [
                sys.executable,
                str(VALIDATOR),
                "--story",
                str(STORY),
                "--quiz",
                str(path),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )


class ValidateQuizTest(unittest.TestCase):
    def setUp(self) -> None:
        self.quiz = json.loads(QUIZ.read_text(encoding="utf-8"))

    def assert_fails(self, expected: str) -> None:
        result = run_validator(self.quiz)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn(expected, result.stderr)

    def test_canonical_quiz_is_valid(self) -> None:
        result = run_validator(self.quiz)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("OK:", result.stdout)

    def test_answer_must_be_one_of_its_choices(self) -> None:
        self.quiz["questions"][0]["answer"] = "not_a_choice"
        self.assert_fails("is not one of its choices")

    def test_scene_id_must_exist_in_story(self) -> None:
        self.quiz["questions"][0]["scene_id"] = "no_such_scene"
        self.assert_fails("is not in the story")

    def test_story_id_must_match(self) -> None:
        self.quiz["story_id"] = "greybox.stage99"
        self.assert_fails("quiz.story_id is")

    def test_duplicate_question_id(self) -> None:
        clone = copy.deepcopy(self.quiz["questions"][0])
        self.quiz["questions"].append(clone)
        self.assert_fails("duplicate question id")

    def test_duplicate_choice_id(self) -> None:
        self.quiz["questions"][0]["choices"][1]["id"] = (
            self.quiz["questions"][0]["choices"][0]["id"]
        )
        self.assert_fails("duplicate choice id")

    def test_story_does_not_embed_quiz(self) -> None:
        story = json.loads(STORY.read_text(encoding="utf-8"))
        for forbidden in ("questions", "quiz", "quiz_id"):
            self.assertNotIn(forbidden, story)


if __name__ == "__main__":
    unittest.main()
