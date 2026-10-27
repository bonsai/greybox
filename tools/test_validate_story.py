#!/usr/bin/env python3
"""Tests for tools/validate_story.py.

Each test copies the canonical story, breaks exactly one rule, and asserts that
the validator exits non-zero with a useful message.

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
VALIDATOR = ROOT / "tools" / "validate_story.py"
STORY = ROOT / "story" / "stage01.json"


def run_validator(story: dict) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "story.json"
        path.write_text(json.dumps(story, ensure_ascii=False, indent=2), encoding="utf-8")
        return subprocess.run(
            [sys.executable, str(VALIDATOR), "--story", str(path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )


class ValidateStoryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.story = json.loads(STORY.read_text(encoding="utf-8"))

    def scene(self, scene_id: str) -> dict:
        return next(s for s in self.story["scenes"] if s["id"] == scene_id)

    def assert_fails(self, expected: str) -> None:
        result = run_validator(self.story)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn(expected, result.stderr)

    def test_canonical_story_is_valid(self) -> None:
        result = run_validator(self.story)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("OK:", result.stdout)

    def test_duplicate_choice_id(self) -> None:
        self.scene("retest_result")["choices"][1]["id"] = "ship_with_evidence"
        self.assert_fails("is used twice")

    def test_unknown_speaker(self) -> None:
        self.scene("ai_report")["speaker"] = "ghost"
        self.assert_fails("unknown speaker 'ghost'")

    def test_unknown_event(self) -> None:
        self.scene("retest_event")["event"] = "not_implemented"
        self.assert_fails("unknown event 'not_implemented'")

    def test_unreachable_scene(self) -> None:
        clone = copy.deepcopy(self.scene("ending_reviewed"))
        clone["id"] = "orphan_scene"
        self.story["scenes"].append(clone)
        self.assert_fails("orphan_scene' is unreachable")

    def test_effect_key_missing_from_initial_state(self) -> None:
        self.scene("decision")["choices"][0]["effects"]["typo_risk"] = 3
        self.assert_fails("is not defined in initial_state")

    def test_cycle_is_rejected(self) -> None:
        self.scene("ai_report")["next"] = "review_request"
        self.assert_fails("cycle detected")

    def test_missing_next_target(self) -> None:
        self.scene("full_review")["next"] = "does_not_exist"
        self.assert_fails("does not exist")


if __name__ == "__main__":
    unittest.main()
