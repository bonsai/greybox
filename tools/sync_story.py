#!/usr/bin/env python3
"""Synchronise the canonical story JSON into the Ren'Py runtime directory.

`story/*.json` is the source of truth. `game/story/*.json` is a generated copy
that Ren'Py packages into builds. Never edit the copy by hand.

Usage:
    python tools/sync_story.py            # copy story/ -> game/story/
    python tools/sync_story.py --check    # fail if the copy is out of date
"""

from __future__ import annotations

import argparse
import filecmp
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIR = ROOT / "story"
TARGET_DIR = ROOT / "game" / "story"

def is_dev_only(name: str) -> bool:
    """Schemas validate content but are not needed by the runtime."""
    return name.endswith("schema.json")


def story_files(source_dir: Path) -> list[Path]:
    return sorted(
        p
        for p in source_dir.glob("*.json")
        if p.is_file() and not is_dev_only(p.name)
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify that game/story matches story/ without writing anything",
    )
    args = parser.parse_args()

    if not SOURCE_DIR.is_dir():
        print(f"error: canonical story directory is missing: {SOURCE_DIR}", file=sys.stderr)
        return 1

    stale: list[str] = []
    copied: list[str] = []

    TARGET_DIR.mkdir(parents=True, exist_ok=True)

    for source in story_files(SOURCE_DIR):
        target = TARGET_DIR / source.name
        if target.is_file() and filecmp.cmp(source, target, shallow=False):
            continue
        if args.check:
            stale.append(source.name)
        else:
            shutil.copyfile(source, target)
            copied.append(source.name)

    extras = [
        target.name
        for target in sorted(TARGET_DIR.glob("*.json"))
        if not is_dev_only(target.name) and not (SOURCE_DIR / target.name).is_file()
    ]

    if args.check:
        if stale:
            for name in stale:
                print(f"out of sync: game/story/{name}", file=sys.stderr)
        if extras:
            for name in extras:
                print(f"stale file: game/story/{name} (no source in story/)", file=sys.stderr)
        if stale or extras:
            print("hint: run `python tools/sync_story.py`", file=sys.stderr)
            return 1
        print(f"game/story is in sync ({len(story_files(SOURCE_DIR))} file(s))")
        return 0

    for name in copied:
        print(f"copied: story/{name} -> game/story/{name}")
    if extras:
        for name in extras:
            print(f"warning: game/story/{name} has no source in story/", file=sys.stderr)
    if not copied:
        print("already in sync")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
