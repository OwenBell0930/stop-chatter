#!/usr/bin/env python3
"""Deterministic artifact gate for the Stop Chatter skill."""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


SCHEMA_VERSION = 1
MAX_TEXT_BYTES = 2 * 1024 * 1024
DEFAULT_IGNORE_PATHS = (".git/**", ".stop-chatter/**")
DEFAULT_PROCESS_PATTERNS = (
    re.compile(r"(?:简洁|精简|高效|不啰嗦).{0,16}(?:版|版本)"),
    re.compile(
        r"\b(?:concise|streamlined|efficient|no[- ]?fluff).{0,24}"
        r"\b(?:version|edition)\b",
        re.IGNORECASE,
    ),
)


class ConfigError(ValueError):
    """Raised when the transient target state is invalid."""


@dataclass(frozen=True)
class Violation:
    code: str
    path: str
    message: str
    line: int | None = None
    term: str | None = None


def path_matches(path: str, pattern: str) -> bool:
    normalized_path = PurePosixPath(path).as_posix().lstrip("./")
    normalized_pattern = PurePosixPath(pattern).as_posix().lstrip("./")
    if normalized_pattern.endswith("/**"):
        prefix = normalized_pattern[:-3].rstrip("/")
        if normalized_path == prefix or normalized_path.startswith(prefix + "/"):
            return True
    return fnmatch.fnmatchcase(normalized_path, normalized_pattern)


def _require_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{field} must be a non-empty string")
    return value.strip()


def _require_string_list(value: Any, field: str, *, non_empty: bool = False) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ConfigError(f"{field} must be a list of non-empty strings")
    if non_empty and not value:
        raise ConfigError(f"{field} must not be empty")
    return [item.strip() for item in value]


def load_state(path: Path) -> dict[str, Any]:
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"state file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"state file is not valid JSON: {exc}") from exc
    if not isinstance(state, dict):
        raise ConfigError("state root must be an object")
    validate_state(state)
    return state


def validate_state(state: dict[str, Any]) -> None:
    if state.get("schema_version") != SCHEMA_VERSION:
        raise ConfigError(f"schema_version must be {SCHEMA_VERSION}")
    if state.get("ready") is not True:
        raise ConfigError("state.ready must be true after replacing all template values")

    target = state.get("active_target")
    if not isinstance(target, dict):
        raise ConfigError("active_target must be an object")
    _require_string(target.get("goal"), "active_target.goal")

    requirements = target.get("requirements")
    if not isinstance(requirements, list) or not requirements:
        raise ConfigError("active_target.requirements must be a non-empty list")
    requirement_ids: set[str] = set()
    for index, requirement in enumerate(requirements):
        if not isinstance(requirement, dict):
            raise ConfigError(f"active_target.requirements[{index}] must be an object")
        requirement_id = _require_string(requirement.get("id"), f"requirements[{index}].id")
        if requirement_id in requirement_ids:
            raise ConfigError(f"duplicate requirement id: {requirement_id}")
        requirement_ids.add(requirement_id)
        _require_string(requirement.get("text"), f"requirements[{index}].text")
        _require_string_list(requirement.get("paths"), f"requirements[{index}].paths", non_empty=True)

    meta_constraints = target.get("meta_constraints", [])
    if not isinstance(meta_constraints, list):
        raise ConfigError("active_target.meta_constraints must be a list")
    for index, constraint in enumerate(meta_constraints):
        if not isinstance(constraint, dict):
            raise ConfigError(f"meta_constraints[{index}] must be an object")
        _require_string(constraint.get("id"), f"meta_constraints[{index}].id")
        _require_string(constraint.get("text"), f"meta_constraints[{index}].text")
        _require_string_list(
            constraint.get("leak_markers", []),
            f"meta_constraints[{index}].leak_markers",
        )

    retired = state.get("retired", [])
    if not isinstance(retired, list):
        raise ConfigError("retired must be a list")
    for index, item in enumerate(retired):
        if not isinstance(item, dict):
            raise ConfigError(f"retired[{index}] must be an object")
        _require_string(item.get("id"), f"retired[{index}].id")
        _require_string(item.get("label"), f"retired[{index}].label")
        _require_string_list(item.get("aliases", []), f"retired[{index}].aliases")
        if item.get("scope") != "task":
            raise ConfigError(f"retired[{index}].scope must be 'task'")

    delivery = state.get("delivery", {})
    if not isinstance(delivery, dict):
        raise ConfigError("delivery must be an object")
    _require_string_list(delivery.get("ignore_paths", []), "delivery.ignore_paths")
    _require_string_list(
        delivery.get("allow_process_trace_paths", []),
        "delivery.allow_process_trace_paths",
    )
    exceptions = delivery.get("exceptions", [])
    if not isinstance(exceptions, list):
        raise ConfigError("delivery.exceptions must be a list")
    for index, exception in enumerate(exceptions):
        if not isinstance(exception, dict):
            raise ConfigError(f"delivery.exceptions[{index}] must be an object")
        _require_string(exception.get("path"), f"exceptions[{index}].path")
        codes = _require_string_list(
            exception.get("codes"), f"exceptions[{index}].codes", non_empty=True
        )
        if any(code not in {"STC001", "STC003"} for code in codes):
            raise ConfigError(f"exceptions[{index}].codes may contain only STC001 or STC003")
        terms = _require_string_list(exception.get("terms", []), f"exceptions[{index}].terms")
        if "STC001" in codes and not terms:
            raise ConfigError(f"exceptions[{index}].terms is required for STC001")
        requirement_id = _require_string(
            exception.get("requirement_id"), f"exceptions[{index}].requirement_id"
        )
        if requirement_id not in requirement_ids:
            raise ConfigError(
                f"exceptions[{index}].requirement_id is not active: {requirement_id}"
            )
        _require_string(exception.get("reason"), f"exceptions[{index}].reason")


def _run_git(root: Path, arguments: list[str]) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(root), *arguments],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        message = result.stderr.decode("utf-8", errors="replace").strip()
        raise ConfigError(message or f"git command failed: {' '.join(arguments)}")
    return [
        item.decode("utf-8", errors="surrogateescape")
        for item in result.stdout.split(b"\0")
        if item
    ]


def discover_paths(root: Path, mode: str, explicit_paths: Iterable[str]) -> list[str]:
    explicit = list(explicit_paths)
    if explicit:
        resolved_root = root.resolve()
        normalized: set[str] = set()
        for raw_path in explicit:
            candidate = Path(raw_path)
            resolved = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
            try:
                relative = resolved.relative_to(resolved_root)
            except ValueError as exc:
                raise ConfigError(f"path is outside root: {raw_path}") from exc
            normalized.add(relative.as_posix())
        return sorted(normalized)

    if mode == "all":
        return sorted(
            path.relative_to(root).as_posix()
            for path in root.rglob("*")
            if path.is_file() and not path.is_symlink()
        )

    inside = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--is-inside-work-tree"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if inside.returncode != 0:
        raise ConfigError("root is not a Git worktree; pass explicit paths or use --mode all")

    paths: set[str] = set()
    if mode == "staged":
        paths.update(_run_git(root, ["diff", "--cached", "--name-only", "-z", "--diff-filter=ACMRT"]))
    else:
        paths.update(_run_git(root, ["diff", "--name-only", "-z", "--diff-filter=ACMRT"]))
        paths.update(
            _run_git(root, ["diff", "--cached", "--name-only", "-z", "--diff-filter=ACMRT"])
        )
        paths.update(_run_git(root, ["ls-files", "--others", "--exclude-standard", "-z"]))
    return sorted(paths)


def _is_ignored(path: str, state: dict[str, Any], state_path: Path, root: Path) -> bool:
    patterns = [*DEFAULT_IGNORE_PATHS, *state.get("delivery", {}).get("ignore_paths", [])]
    try:
        relative_state = state_path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        relative_state = ""
    return path == relative_state or any(path_matches(path, pattern) for pattern in patterns)


def _mapped_requirements(path: str, state: dict[str, Any]) -> list[str]:
    mapped: list[str] = []
    for requirement in state["active_target"]["requirements"]:
        if any(path_matches(path, pattern) for pattern in requirement["paths"]):
            mapped.append(requirement["id"])
    return mapped


def _exception_allows(
    state: dict[str, Any], path: str, code: str, term: str | None = None
) -> bool:
    for exception in state.get("delivery", {}).get("exceptions", []):
        if code not in exception["codes"] or not path_matches(path, exception["path"]):
            continue
        if code == "STC001":
            allowed_terms = {item.casefold() for item in exception.get("terms", [])}
            if term is None or term.casefold() not in allowed_terms:
                continue
        return True
    return False


def _line_matches(lines: list[str], needle: str) -> Iterable[tuple[int, str]]:
    folded_needle = needle.casefold()
    for line_number, line in enumerate(lines, start=1):
        if folded_needle in line.casefold():
            yield line_number, line


def check_artifacts(
    root: Path, state_path: Path, state: dict[str, Any], paths: Iterable[str]
) -> tuple[list[Violation], int]:
    violations: list[Violation] = []
    checked = 0
    retired_terms: list[str] = []
    for item in state.get("retired", []):
        retired_terms.extend([item["label"], *item.get("aliases", [])])
    retired_terms = list(dict.fromkeys(retired_terms))

    leak_markers: list[str] = []
    for constraint in state["active_target"].get("meta_constraints", []):
        leak_markers.extend(constraint.get("leak_markers", []))
    leak_markers = list(dict.fromkeys(leak_markers))
    process_trace_allowlist = state.get("delivery", {}).get("allow_process_trace_paths", [])

    seen: set[tuple[str, str, int | None, str | None]] = set()
    for relative_path in paths:
        relative_path = PurePosixPath(relative_path).as_posix().lstrip("./")
        if _is_ignored(relative_path, state, state_path, root):
            continue
        artifact = root / relative_path
        if not artifact.exists() or not artifact.is_file() or artifact.is_symlink():
            continue
        checked += 1

        if not _mapped_requirements(relative_path, state):
            violations.append(
                Violation("STC002", relative_path, "changed artifact maps to no active requirement")
            )

        try:
            raw = artifact.read_bytes()
        except OSError as exc:
            violations.append(Violation("STC004", relative_path, f"cannot read artifact: {exc}"))
            continue
        if len(raw) > MAX_TEXT_BYTES:
            violations.append(
                Violation("STC004", relative_path, f"artifact exceeds {MAX_TEXT_BYTES} bytes")
            )
            continue
        if b"\0" in raw[:8192]:
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            violations.append(Violation("STC004", relative_path, "artifact is not UTF-8 text"))
            continue

        lines = text.splitlines()
        for term in retired_terms:
            if _exception_allows(state, relative_path, "STC001", term):
                continue
            for line_number, _ in _line_matches(lines, term):
                key = ("STC001", relative_path, line_number, term.casefold())
                if key in seen:
                    continue
                seen.add(key)
                violations.append(
                    Violation(
                        "STC001",
                        relative_path,
                        "retired concept remains in artifact",
                        line=line_number,
                        term=term,
                    )
                )

        process_allowed = any(
            path_matches(relative_path, pattern) for pattern in process_trace_allowlist
        ) or _exception_allows(state, relative_path, "STC003")
        if process_allowed:
            continue
        for marker in leak_markers:
            for line_number, _ in _line_matches(lines, marker):
                key = ("STC003", relative_path, line_number, marker.casefold())
                if key in seen:
                    continue
                seen.add(key)
                violations.append(
                    Violation(
                        "STC003",
                        relative_path,
                        "meta-instruction leaked into artifact",
                        line=line_number,
                        term=marker,
                    )
                )
        for line_number, line in enumerate(lines, start=1):
            for pattern in DEFAULT_PROCESS_PATTERNS:
                match = pattern.search(line)
                if not match:
                    continue
                marker = match.group(0)
                key = ("STC003", relative_path, line_number, marker.casefold())
                if key in seen:
                    continue
                seen.add(key)
                violations.append(
                    Violation(
                        "STC003",
                        relative_path,
                        "compliance-style version label remains in artifact",
                        line=line_number,
                        term=marker,
                    )
                )

    return violations, checked


def command_init(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    if not root.exists() or not root.is_dir():
        raise ConfigError(f"root directory does not exist: {root}")
    source = Path(__file__).resolve().parents[1] / "templates" / "state.example.json"
    if not source.is_file():
        raise ConfigError(f"state template not found: {source}")
    state_dir = root / ".stop-chatter"
    state_path = state_dir / "state.json"
    if state_path.exists():
        raise ConfigError(f"refusing to overwrite existing state: {state_path}")
    state_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, state_path)
    ignore_file = state_dir / ".gitignore"
    if not ignore_file.exists():
        ignore_file.write_text("state.json\n", encoding="utf-8")
    print(f"Created transient state: {state_path}")
    print("Replace template values before running check.")
    return 0


def command_check(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    if not root.exists() or not root.is_dir():
        raise ConfigError(f"root directory does not exist: {root}")
    state_path = Path(args.state)
    if not state_path.is_absolute():
        state_path = root / state_path
    state = load_state(state_path)
    paths = discover_paths(root, args.mode, args.paths)
    violations, checked = check_artifacts(root, state_path, state, paths)
    payload = {
        "ok": not violations,
        "checked_files": checked,
        "violations": [asdict(violation) for violation in violations],
    }
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif violations:
        print(f"FAIL Stop Chatter: {len(violations)} violation(s) in {checked} file(s)")
        for violation in violations:
            location = violation.path
            if violation.line is not None:
                location += f":{violation.line}"
            suffix = f" [{violation.term}]" if violation.term else ""
            print(f"{violation.code} {location}: {violation.message}{suffix}")
    else:
        print(f"PASS Stop Chatter: {checked} artifact(s) map to the active target")
    return 1 if violations else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prune correction residue from final artifacts.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="create a transient target-state file")
    init_parser.add_argument("--root", default=".", help="project root")
    init_parser.set_defaults(handler=command_init)

    check_parser = subparsers.add_parser("check", help="check artifacts against active target")
    check_parser.add_argument("paths", nargs="*", help="explicit paths relative to root")
    check_parser.add_argument("--root", default=".", help="project root")
    check_parser.add_argument(
        "--state", default=".stop-chatter/state.json", help="target-state JSON path"
    )
    check_parser.add_argument(
        "--mode",
        choices=("worktree", "staged", "all"),
        default="worktree",
        help="artifact discovery mode when explicit paths are absent",
    )
    check_parser.add_argument("--format", choices=("human", "json"), default="human")
    check_parser.set_defaults(handler=command_check)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.handler(args)
    except ConfigError as exc:
        if getattr(args, "format", "human") == "json":
            print(json.dumps({"ok": False, "config_error": str(exc)}, ensure_ascii=False))
        else:
            print(f"CONFIG_ERROR Stop Chatter: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
