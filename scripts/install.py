#!/usr/bin/env python3
"""Install Stop Chatter without overwriting existing host configuration."""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path


SKILL_NAME = "stop-chatter"
PAYLOAD = (
    "SKILL.md",
    "LICENSE",
    "agents/openai.yaml",
    "assets/logo.svg",
    "scripts/stop_chatter.py",
    "scripts/install.py",
    "references/protocol.md",
    "references/host-setup.md",
    "templates/state.example.json",
)


def requested_hosts(host: str) -> tuple[str, ...]:
    return ("cursor", "codex", "claude") if host == "all" else (host,)


def destinations(host: str, scope: str, target: Path | None) -> list[tuple[str, Path]]:
    hosts = requested_hosts(host)
    result: list[tuple[str, Path]] = []
    if scope == "project":
        assert target is not None
        if "cursor" in hosts or "codex" in hosts:
            labels = "+".join(item for item in ("cursor", "codex") if item in hosts)
            result.append((labels, target / ".agents" / "skills" / SKILL_NAME))
        if "claude" in hosts:
            result.append(("claude", target / ".claude" / "skills" / SKILL_NAME))
    else:
        home = Path.home()
        mapping = {
            "cursor": home / ".cursor" / "skills" / SKILL_NAME,
            "codex": home / ".codex" / "skills" / SKILL_NAME,
            "claude": home / ".claude" / "skills" / SKILL_NAME,
        }
        result.extend((item, mapping[item]) for item in hosts)
    return result


def copy_payload(source: Path, temporary: Path) -> None:
    for relative in PAYLOAD:
        origin = source / relative
        if not origin.is_file():
            raise RuntimeError(f"missing package file: {origin}")
        destination = temporary / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(origin, destination)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Install the Stop Chatter Agent Skill.")
    parser.add_argument("--host", choices=("cursor", "codex", "claude", "all"), required=True)
    parser.add_argument("--scope", choices=("project", "user"), default="project")
    parser.add_argument("--target", help="project root; defaults to current directory")
    parser.add_argument("--dry-run", action="store_true", help="print destinations without writing")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    source = Path(__file__).resolve().parents[1]
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
    existing = [destination for _, destination in planned if destination.exists()]
    if existing:
        for destination in existing:
            print(f"ERROR refusing to overwrite: {destination}", file=sys.stderr)
        return 2

    for relative in PAYLOAD:
        if not (source / relative).is_file():
            print(f"ERROR package is incomplete: {source / relative}", file=sys.stderr)
            return 2

    if args.dry_run:
        for label, destination in planned:
            print(f"DRY_RUN {label}: {destination}")
        return 0

    installed: list[Path] = []
    temporary_paths: list[Path] = []
    try:
        for label, destination in planned:
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = Path(
                tempfile.mkdtemp(prefix=".stop-chatter-install-", dir=destination.parent)
            )
            temporary_paths.append(temporary)
            copy_payload(source, temporary)
            temporary.rename(destination)
            temporary_paths.remove(temporary)
            installed.append(destination)
            print(f"INSTALLED {label}: {destination}")
    except Exception as exc:
        for temporary in temporary_paths:
            shutil.rmtree(temporary, ignore_errors=True)
        for destination in reversed(installed):
            shutil.rmtree(destination, ignore_errors=True)
        print(f"ERROR installation rolled back: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
