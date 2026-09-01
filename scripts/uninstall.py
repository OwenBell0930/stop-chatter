#!/usr/bin/env python3
"""Safely remove exact Stop Chatter installations and nothing else."""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

from install import destinations


SKILL_NAME_PATTERN = re.compile(r"(?m)^name:\s*stop-chatter\s*$")


def is_stop_chatter_installation(destination: Path) -> bool:
    if destination.is_symlink() or not destination.is_dir():
        return False
    skill = destination / "SKILL.md"
    checker = destination / "scripts" / "stop_chatter.py"
    if not skill.is_file() or not checker.is_file():
        return False
    try:
        return SKILL_NAME_PATTERN.search(skill.read_text(encoding="utf-8")) is not None
    except (OSError, UnicodeDecodeError):
        return False


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Uninstall the Stop Chatter Agent Skill.")
    parser.add_argument("--host", choices=("cursor", "codex", "claude", "all"), required=True)
    parser.add_argument("--scope", choices=("project", "user"), default="project")
    parser.add_argument("--target", help="project root; defaults to current directory")
    parser.add_argument("--dry-run", action="store_true", help="print exact removals without writing")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.scope == "project":
        target = Path(args.target or ".").resolve()
        if not target.exists() or not target.is_dir():
            print(f"ERROR project target does not exist: {target}", file=sys.stderr)
            return 2
    else:
        if args.target:
            print("ERROR --target is only valid for project scope", file=sys.stderr)
            return 2
        target = None

    planned = destinations(args.host, args.scope, target)
    existing = [(label, destination) for label, destination in planned if destination.exists()]
    unsafe = [destination for _, destination in existing if not is_stop_chatter_installation(destination)]
    if unsafe:
        for destination in unsafe:
            print(f"ERROR refusing to remove unverified destination: {destination}", file=sys.stderr)
        return 2

    if not existing:
        for label, destination in planned:
            print(f"NOT_INSTALLED {label}: {destination}")
        return 0

    if args.dry_run:
        for label, destination in existing:
            print(f"DRY_RUN_REMOVE {label}: {destination}")
        return 0

    for label, destination in existing:
        try:
            shutil.rmtree(destination)
        except OSError as exc:
            print(f"ERROR failed to remove {destination}: {exc}", file=sys.stderr)
            return 1
        print(f"REMOVED {label}: {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
