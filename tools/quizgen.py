#!/usr/bin/env python3
"""Fill a GREYBOX quiz from stage settings, using an LLM when questions run out.

Settings are YAML (`story/config/*.yaml`), data is JSON (`story/*.json`).
This tool is the "LLM patch": it reads the format + the goal list, notices
which scenes have no question yet, asks an OpenAI-compatible model for more,
checks the answer against the story, and appends what survives.

When the model is unavailable, `exhausted.fallback` decides what happens:

  recycle : print a review set of the least-covered questions (no data change)
  stop    : exit 2 with a report, so a human decides

Usage:
    python tools/quizgen.py --check              # config <-> data consistency
    python tools/quizgen.py --dry-run            # show the prompt, call nothing
    python tools/quizgen.py                      # generate missing questions
    python tools/quizgen.py --count 2 --dry-run

Environment (names come from the config, these are the defaults):
    LLM_BASE_URL   e.g. https://api.openai.com/v1
    LLM_API_KEY    bearer token
    LLM_MODEL      model id
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / "story" / "config" / "stage01.yaml"
ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")

errors: list[str] = []
warnings: list[str] = []


def error(message: str) -> None:
    errors.append(message)


def warn(message: str) -> None:
    warnings.append(message)


# --------------------------------------------------------------------------- io


def load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, document: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    tmp.replace(path)


# ------------------------------------------------------------------- selection


def quiz_targets(story: dict[str, Any], quiz_config: dict[str, Any]) -> list[str]:
    """Scene ids that may carry a question, in story order."""
    wanted = set(quiz_config.get("scene_types", ["choice", "ending"]))
    return [scene["id"] for scene in story["scenes"] if scene["type"] in wanted]


def coverage(quiz: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for question in quiz.get("questions", []):
        counts[question["scene_id"]] = counts.get(question["scene_id"], 0) + 1
    return counts


def scenes_needing_questions(
    story: dict[str, Any],
    quiz: dict[str, Any],
    quiz_config: dict[str, Any],
    limit: int,
) -> list[str]:
    per_scene = int(quiz_config.get("questions_per_scene", 1))
    counts = coverage(quiz)
    needed: list[str] = []
    for scene_id in quiz_targets(story, quiz_config):
        if counts.get(scene_id, 0) < per_scene:
            needed.append(scene_id)
    return needed[:limit]


def tag_coverage(quiz: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for question in quiz.get("questions", []):
        for tag in question.get("tags", []):
            counts[tag] = counts.get(tag, 0) + 1
    return counts


def normalise_prompt(text: str) -> str:
    return re.sub(r"[\s　。、．，,.!?！？「」『』()（）]+", "", text or "").lower()


def validate_candidate(
    question: dict[str, Any],
    allowed_scene_ids: set[str],
    existing_ids: set[str],
    existing_prompts: set[str],
) -> list[str]:
    problems: list[str] = []
    question_id = question.get("id")
    if not isinstance(question_id, str) or not ID_RE.match(question_id):
        problems.append("id must be snake_case")
    elif question_id in existing_ids:
        problems.append(f"id '{question_id}' already exists")

    if question.get("scene_id") not in allowed_scene_ids:
        problems.append(f"scene_id '{question.get('scene_id')}' is not an allowed scene")

    prompt = question.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        problems.append("prompt is empty")
    elif normalise_prompt(prompt) in existing_prompts:
        problems.append("prompt duplicates an existing question")

    choices = question.get("choices")
    if not isinstance(choices, list) or len(choices) < 2:
        problems.append("needs at least 2 choices")
        choices = []
    choice_ids = [choice.get("id") for choice in choices]
    if len(choice_ids) != len(set(choice_ids)):
        problems.append("duplicate choice id")
    for choice in choices:
        if not isinstance(choice.get("id"), str) or not ID_RE.match(choice["id"]):
            problems.append("choice id must be snake_case")
        if not str(choice.get("text", "")).strip():
            problems.append("choice text is empty")

    if question.get("answer") not in choice_ids:
        problems.append("answer must be one of the choice ids")

    if not str(question.get("explanation", "")).strip():
        problems.append("explanation is empty")

    return problems


# ---------------------------------------------------------------------- prompt


def scene_context(story: dict[str, Any], scene_ids: list[str]) -> str:
    scene_map = {scene["id"]: scene for scene in story["scenes"]}
    blocks = []
    for scene_id in scene_ids:
        scene = scene_map[scene_id]
        block = [f"- id: {scene['id']}  type: {scene['type']}"]
        if scene.get("speaker"):
            block.append(f"  speaker: {scene['speaker']}")
        if scene.get("title"):
            block.append(f"  title: {scene['title']}")
        block.append(f"  text: {scene.get('text', '')}")
        for choice in scene.get("choices", []):
            block.append(f"  choice {choice['id']}: {choice['text']}")
        blocks.append("\n".join(block))
    return "\n".join(blocks)


def render(template: str, values: dict[str, str]) -> str:
    for key, value in values.items():
        template = template.replace("{{" + key + "}}", value)
    return template


def build_messages(
    fmt: dict[str, Any],
    config: dict[str, Any],
    story: dict[str, Any],
    quiz: dict[str, Any],
    scene_ids: list[str],
    count: int,
) -> list[dict[str, str]]:
    rules = "\n".join(f"  {rule}" for rule in fmt.get("rules", []))
    goals = "\n".join(
        f"  - {goal['id']}: {goal['description']} (tags: {', '.join(goal.get('quiz_tags', []))})"
        for goal in config.get("goals", [])
    )
    existing = "\n".join(
        f"  - {question['scene_id']}: {question['prompt']}"
        for question in quiz.get("questions", [])
    ) or "  (none)"
    format_block = "\n".join(
        f"  {name}: {json.dumps(spec, ensure_ascii=False)}"
        for name, spec in fmt.get("question_types", {}).items()
    )
    style = fmt.get("style", {})
    format_block += (
        f"\n  style: language={style.get('language')}, "
        f"prompt<={style.get('prompt_max_chars')} chars, "
        f"choice<={style.get('choice_max_chars')} chars, "
        f"explanation<={style.get('explanation_max_chars')} chars"
    )

    values = {
        "rules": rules,
        "goals": goals,
        "scene": scene_context(story, scene_ids),
        "existing": existing,
        "count": str(count),
        "format": format_block,
    }
    prompt = fmt.get("prompt", {})
    return [
        {"role": "system", "content": render(prompt.get("system", ""), values)},
        {"role": "user", "content": render(prompt.get("user", ""), values)},
    ]


# ------------------------------------------------------------------------- llm


class LlmUnavailable(RuntimeError):
    pass


def call_llm(
    messages: list[dict[str, str]], settings: dict[str, Any]
) -> str:
    base_url = os.environ.get(settings.get("base_url_env", "LLM_BASE_URL"), "").rstrip("/")
    api_key = os.environ.get(settings.get("api_key_env", "LLM_API_KEY"), "")
    model = os.environ.get(settings.get("model_env", "LLM_MODEL"), "")

    missing = [
        name
        for name, value in (
            (settings.get("base_url_env", "LLM_BASE_URL"), base_url),
            (settings.get("api_key_env", "LLM_API_KEY"), api_key),
            (settings.get("model_env", "LLM_MODEL"), model),
        )
        if not value
    ]
    if missing:
        raise LlmUnavailable("missing environment variable(s): " + ", ".join(missing))

    body = json.dumps(
        {
            "model": model,
            "messages": messages,
            "temperature": settings.get("temperature", 0.6),
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        base_url + "/chat/completions",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(
            request, timeout=int(settings.get("timeout_seconds", 90))
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:400]
        raise RuntimeError(f"HTTP {exc.code} from {base_url}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise LlmUnavailable(f"cannot reach {base_url}: {exc.reason}") from exc

    try:
        return payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"unexpected response shape: {str(payload)[:300]}") from exc


def parse_questions(text: str) -> list[dict[str, Any]]:
    cleaned = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    start_candidates = [i for i in (cleaned.find("["), cleaned.find("{")) if i >= 0]
    if not start_candidates:
        raise ValueError("no JSON found in the response")
    start = min(start_candidates)
    end = max(cleaned.rfind("]"), cleaned.rfind("}"))
    if end <= start:
        raise ValueError("unterminated JSON in the response")
    document = json.loads(cleaned[start : end + 1])
    if isinstance(document, dict):
        document = document.get("questions", [])
    if not isinstance(document, list):
        raise ValueError("response is not a JSON array of questions")
    return [item for item in document if isinstance(item, dict)]


# ------------------------------------------------------------------------ check


def check_config(
    config: dict[str, Any],
    story: dict[str, Any],
    quiz: dict[str, Any],
    fmt: dict[str, Any],
) -> None:
    if config.get("story", {}).get("id") != story.get("story_id"):
        error(
            f"config story.id is '{config.get('story', {}).get('id')}' "
            f"but the story is '{story.get('story_id')}'"
        )

    if fmt.get("format_id") != "greybox.quiz.format.v1":
        warn(f"unexpected format_id: {fmt.get('format_id')!r}")

    configured = config.get("characters", {})
    actual = story.get("characters", {})
    for character_id, spec in configured.items():
        if character_id not in actual:
            error(f"character '{character_id}' is in the config but not in the story")
            continue
        for field in ("name", "role"):
            if spec.get(field) != actual[character_id].get(field):
                error(
                    f"character '{character_id}'.{field} differs: "
                    f"config={spec.get(field)!r} story={actual[character_id].get(field)!r}"
                )
    for character_id in actual:
        if character_id not in configured:
            warn(f"character '{character_id}' is in the story but not in the config")

    quiz_config = config.get("quiz", {})
    minimum = int(quiz_config.get("minimum_total", 0))
    if len(quiz.get("questions", [])) < minimum:
        error(
            f"quiz has {len(quiz.get('questions', []))} question(s), "
            f"minimum_total is {minimum}"
        )

    counts = tag_coverage(quiz)
    for tag in quiz_config.get("require_tags", []):
        if counts.get(tag, 0) == 0:
            error(f"no question covers required tag '{tag}'")


def report_coverage(story: dict[str, Any], quiz: dict[str, Any], config: dict[str, Any]) -> None:
    quiz_config = config.get("quiz", {})
    counts = coverage(quiz)
    targets = quiz_targets(story, quiz_config)
    print(f"questions: {len(quiz.get('questions', []))} / target {quiz_config.get('target_total')}")
    for scene_id in targets:
        marker = "ok " if counts.get(scene_id, 0) >= int(quiz_config.get("questions_per_scene", 1)) else "gap"
        print(f"  [{marker}] {scene_id}: {counts.get(scene_id, 0)}")
    tags = tag_coverage(quiz)
    print("tags: " + ", ".join(f"{tag}={count}" for tag, count in sorted(tags.items())))


def recycle_set(quiz: dict[str, Any], count: int) -> list[dict[str, Any]]:
    """Least-covered questions, as a review set. Does not modify the quiz."""
    seen: dict[str, int] = {}
    for question in quiz.get("questions", []):
        seen[question["scene_id"]] = seen.get(question["scene_id"], 0) + 1
    ordered = sorted(
        quiz.get("questions", []),
        key=lambda q: (seen.get(q["scene_id"], 0), q.get("scene_id", "")),
    )
    return ordered[:count]


# ------------------------------------------------------------------------- main


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--count", type=int, default=None, help="how many to generate")
    parser.add_argument("--check", action="store_true", help="config <-> data consistency only")
    parser.add_argument("--dry-run", action="store_true", help="print the prompt, call nothing")
    args = parser.parse_args()

    for path in (args.config,):
        if not path.is_file():
            print(f"error: config not found: {path}", file=sys.stderr)
            return 1

    config = load_yaml(args.config)
    story_path = ROOT / config["story"]["story_file"]
    quiz_path = ROOT / config["story"]["quiz_file"]
    format_path = ROOT / config["story"]["format_file"]
    for path in (story_path, quiz_path, format_path):
        if not path.is_file():
            print(f"error: file not found: {path}", file=sys.stderr)
            return 1

    story = load_json(story_path)
    quiz = load_json(quiz_path)
    fmt = load_yaml(format_path)

    check_config(config, story, quiz, fmt)

    if args.check:
        report_coverage(story, quiz, config)
        for message in warnings:
            print(f"WARN   {message}", file=sys.stderr)
        for message in errors:
            print(f"ERROR  {message}", file=sys.stderr)
        if errors:
            print(f"\nFAILED: {len(errors)} error(s)", file=sys.stderr)
            return 1
        print("OK: settings and data agree")
        return 0

    quiz_config = config.get("quiz", {})
    remaining = int(quiz_config.get("target_total", 0)) - len(quiz.get("questions", []))
    wanted = args.count if args.count is not None else remaining
    wanted = min(wanted, int(quiz_config.get("max_generated_per_run", 4)))
    scene_ids = scenes_needing_questions(story, quiz, quiz_config, max(wanted, 0))

    if not scene_ids or wanted <= 0:
        print("no missing questions; nothing to generate")
        return 0

    wanted = min(wanted, len(scene_ids))
    messages = build_messages(fmt, config, story, quiz, scene_ids, wanted)

    if args.dry_run:
        for message in messages:
            print(f"--- {message['role']} ---")
            print(message["content"])
        print(f"\n(scenes: {', '.join(scene_ids)}; count: {wanted})")
        return 0

    settings = config.get("generation", {})
    attempts = int(settings.get("max_attempts", 2))
    accepted: list[dict[str, Any]] = []
    feedback = ""
    failure = ""

    for attempt in range(1, attempts + 1):
        payload = messages
        if feedback:
            payload = messages + [
                {
                    "role": "user",
                    "content": "The previous output was rejected:\n" + feedback
                    + "\nReturn the corrected JSON array only.",
                }
            ]
        try:
            raw = call_llm(payload, settings)
            candidates = parse_questions(raw)
        except LlmUnavailable as exc:
            failure = str(exc)
            break
        except (RuntimeError, ValueError, json.JSONDecodeError) as exc:
            failure = f"attempt {attempt}: {exc}"
            feedback = str(exc)
            continue

        existing_ids = {question["id"] for question in quiz.get("questions", [])}
        existing_prompts = {
            normalise_prompt(question["prompt"]) for question in quiz.get("questions", [])
        }
        problems: list[str] = []
        for candidate in candidates:
            found = validate_candidate(
                candidate, set(scene_ids), existing_ids, existing_prompts
            )
            if found:
                problems.append(f"{candidate.get('id')}: " + "; ".join(found))
                continue
            existing_ids.add(candidate["id"])
            existing_prompts.add(normalise_prompt(candidate["prompt"]))
            accepted.append(candidate)
            if len(accepted) >= wanted:
                break

        if accepted:
            break
        failure = "all candidates were rejected"
        feedback = "\n".join(problems) or failure

    if not accepted:
        print(f"could not generate questions: {failure}", file=sys.stderr)
        policy = config.get("quiz", {}).get("when_exhausted", "generate")
        fallback = config.get("exhausted", {}).get("fallback", "stop")
        if policy == "recycle" or fallback == "recycle":
            count = int(config.get("exhausted", {}).get("recycle_count", 3))
            print("\nfallback: review set (no data written)")
            for question in recycle_set(quiz, count):
                print(f"  - [{question['scene_id']}] {question['prompt']}")
        return 2

    quiz["questions"].extend(accepted)
    write_json(quiz_path, quiz)
    print(f"added {len(accepted)} question(s) to {quiz_path.relative_to(ROOT)}")
    for question in accepted:
        print(f"  + {question['id']} [{question['scene_id']}]")

    verify = ROOT / "tools" / "validate_quiz.py"
    result = subprocess.run(
        [
            sys.executable,
            str(verify),
            "--story",
            str(story_path),
            "--quiz",
            str(quiz_path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    sys.stderr.write(result.stderr)
    sys.stdout.write(result.stdout)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
