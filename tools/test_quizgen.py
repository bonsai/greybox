#!/usr/bin/env python3
"""Tests for tools/quizgen.py (pure logic; no network).

    python -m unittest discover -s tools -p "test_*.py"
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import quizgen  # noqa: E402

STORY = json.loads((ROOT / "story" / "stage01.json").read_text(encoding="utf-8"))
QUIZ = json.loads((ROOT / "story" / "quiz.stage01.json").read_text(encoding="utf-8"))
CONFIG = quizgen.load_yaml(ROOT / "story" / "config" / "stage01.yaml")


def fresh() -> None:
    quizgen.errors.clear()
    quizgen.warnings.clear()


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    # The CLI prints Japanese; force UTF-8 so the test decodes what it wrote.
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    return subprocess.run(
        [sys.executable, str(ROOT / "tools" / "quizgen.py"), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
    )


def candidate(**overrides: object) -> dict:
    question = {
        "id": "q_new_idea",
        "scene_id": "test_result",
        "prompt": "ゼロ入力の不具合を見つけたあと、最初に何をするべきか。",
        "choices": [
            {"id": "ask_fix", "text": "AI に修正を依頼し、再テストする"},
            {"id": "ship", "text": "そのままリリースする"},
        ],
        "answer": "ask_fix",
        "explanation": "不具合を見つけた時点では、まだ根拠が揃っていない。",
        "tags": ["verification"],
    }
    question.update(overrides)
    return question


class QuizGenTest(unittest.TestCase):
    def setUp(self) -> None:
        fresh()

    def test_targets_are_choice_and_ending_scenes(self) -> None:
        targets = quizgen.quiz_targets(STORY, CONFIG["quiz"])
        types = {s["id"]: s["type"] for s in STORY["scenes"]}
        self.assertTrue(targets)
        for scene_id in targets:
            self.assertIn(types[scene_id], ("choice", "ending"))
        self.assertNotIn("ai_report", targets)

    def test_needing_questions_skips_covered_scenes(self) -> None:
        needed = quizgen.scenes_needing_questions(
            STORY, QUIZ, CONFIG["quiz"], limit=10
        )
        self.assertNotIn("decision", needed)
        self.assertIn("test_result", needed)

    def test_needing_questions_respects_limit(self) -> None:
        needed = quizgen.scenes_needing_questions(STORY, QUIZ, CONFIG["quiz"], limit=1)
        self.assertEqual(len(needed), 1)

    def test_normalise_prompt_ignores_punctuation(self) -> None:
        left = quizgen.normalise_prompt("AI は何を保証する？")
        right = quizgen.normalise_prompt("aiは何を保証する")
        self.assertEqual(left, right)

    def test_valid_candidate_has_no_problems(self) -> None:
        problems = quizgen.validate_candidate(
            candidate(), {"test_result"}, set(), set()
        )
        self.assertEqual(problems, [])

    def test_duplicate_prompt_is_rejected(self) -> None:
        existing = {quizgen.normalise_prompt(QUIZ["questions"][0]["prompt"])}
        problems = quizgen.validate_candidate(
            candidate(prompt=QUIZ["questions"][0]["prompt"]), {"test_result"}, set(), existing
        )
        self.assertTrue(any("duplicates" in p for p in problems))

    def test_answer_outside_choices_is_rejected(self) -> None:
        problems = quizgen.validate_candidate(
            candidate(answer="nowhere"), {"test_result"}, set(), set()
        )
        self.assertTrue(any("answer" in p for p in problems))

    def test_scene_outside_targets_is_rejected(self) -> None:
        problems = quizgen.validate_candidate(
            candidate(scene_id="ai_report"), {"test_result"}, set(), set()
        )
        self.assertTrue(any("not an allowed scene" in p for p in problems))

    def test_duplicate_id_is_rejected(self) -> None:
        problems = quizgen.validate_candidate(
            candidate(), {"test_result"}, {"q_new_idea"}, set()
        )
        self.assertTrue(any("already exists" in p for p in problems))

    def test_tag_coverage_counts_tags(self) -> None:
        counts = quizgen.tag_coverage(QUIZ)
        self.assertGreaterEqual(counts.get("verification", 0), 1)

    def test_recycle_set_prefers_least_covered(self) -> None:
        review = quizgen.recycle_set(QUIZ, 2)
        self.assertEqual(len(review), 2)
        self.assertIn(review[0]["scene_id"], {"decision", "ending_rushed", "retest_result"})

    def test_check_config_detects_character_drift(self) -> None:
        config = copy.deepcopy(CONFIG)
        config["characters"]["ai"]["name"] = "SOME-OTHER-AI"
        quizgen.check_config(
            config,
            STORY,
            QUIZ,
            quizgen.load_yaml(ROOT / "story" / "config" / "quiz.format.yaml"),
        )
        self.assertTrue(any("differs" in e for e in quizgen.errors))

    def test_check_config_detects_missing_tag(self) -> None:
        config = copy.deepcopy(CONFIG)
        config["quiz"]["require_tags"] = ["no_such_tag"]
        quizgen.check_config(
            config,
            STORY,
            QUIZ,
            quizgen.load_yaml(ROOT / "story" / "config" / "quiz.format.yaml"),
        )
        self.assertTrue(any("no_such_tag" in e for e in quizgen.errors))

    def test_cli_check_passes_on_canonical_data(self) -> None:
        result = run_cli("--check")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("OK:", result.stdout)

    def test_cli_dry_run_makes_no_network_call(self) -> None:
        result = run_cli("--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("scene_id", result.stdout)


if __name__ == "__main__":
    unittest.main()
