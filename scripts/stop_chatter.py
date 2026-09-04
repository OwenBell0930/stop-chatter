#!/usr/bin/env python3
"""Deterministic artifact gate for the Stop Chatter skill."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


SCHEMA_VERSION = 1
MAX_TEXT_BYTES = 2 * 1024 * 1024
DEFAULT_IGNORE_PATHS = (".git/**", ".stop-chatter/**")
GLOB_CHARS = frozenset("*?[]")
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
    normalized_path = _norm_rel(path)
    normalized_pattern = _norm_rel(pattern)
    if normalized_pattern.endswith("/**"):
        prefix = normalized_pattern[:-3].rstrip("/")
        if normalized_path == prefix or normalized_path.startswith(prefix + "/"):
            return True
    return fnmatch.fnmatchcase(normalized_path, normalized_pattern)


def _strip_dot_slash_prefix(path: str) -> str:
    text = str(path).replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    return text


def _norm_rel(path: str) -> str:
    normalized = _strip_dot_slash_prefix(PurePosixPath(_strip_dot_slash_prefix(path)).as_posix())
    if normalized in {"", "."}:
        return ""
    return normalized


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


def _require_exact_relative_path(value: str, field: str) -> str:
    text = _require_string(value, field).replace("\\", "/")
    posix = PurePosixPath(text)
    if posix.is_absolute() or text.startswith("/") or text.startswith("~"):
        raise ConfigError(f"{field} must be a relative path inside the project root")
    if ".." in posix.parts:
        raise ConfigError(f"{field} must not contain '..'")
    if any(char in text for char in GLOB_CHARS):
        raise ConfigError(f"{field} must be an exact path, not a glob")
    if text.endswith("/"):
        raise ConfigError(f"{field} must be an exact file path")
    normalized = _norm_rel(text)
    if not normalized or normalized == ".":
        raise ConfigError(f"{field} must be a relative file path")
    return normalized


def _join_under_root(root: Path, relative: str) -> Path:
    rel = PurePosixPath(_norm_rel(relative))
    if rel.is_absolute() or ".." in rel.parts:
        raise ConfigError(f"path is outside root: {relative}")
    parts = [part for part in rel.parts if part not in ("", ".")]
    if not parts:
        raise ConfigError(f"path is outside root: {relative}")
    return root.joinpath(*parts)


def _normalize_user_path(root: Path, raw_path: str) -> str:
    text = str(raw_path).strip()
    if not text:
        raise ConfigError("path must be a non-empty string")
    incoming = Path(text)
    if incoming.is_absolute():
        try:
            relative = os.path.relpath(incoming, start=root.resolve())
        except ValueError as exc:
            raise ConfigError(f"path is outside root: {raw_path}") from exc
        posix = PurePosixPath(relative.replace("\\", "/"))
        if posix.is_absolute() or ".." in posix.parts:
            raise ConfigError(f"path is outside root: {raw_path}")
        normalized = _norm_rel(posix.as_posix())
        if not normalized:
            raise ConfigError(f"path is outside root: {raw_path}")
        return normalized
    return _require_exact_relative_path(text.replace("\\", "/"), "path")


def _lstat(path: Path) -> os.stat_result | None:
    try:
        return path.lstat()
    except FileNotFoundError:
        return None
    except OSError:
        return None


def _lexists(path: Path) -> bool:
    return _lstat(path) is not None


def _relative_parts(relative: str) -> list[str]:
    rel = PurePosixPath(_norm_rel(relative))
    if rel.is_absolute() or ".." in rel.parts:
        raise ConfigError(f"path is outside root: {relative}")
    return [part for part in rel.parts if part not in ("", ".")]


def _symlinked_ancestor(root: Path, relative: str) -> Path | None:
    parts = _relative_parts(relative)
    current = root
    for part in parts[:-1]:
        current = current / part
        info = _lstat(current)
        if info is None:
            return None
        if stat.S_ISLNK(info.st_mode):
            return current
    return None


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
    must_remove = delivery.get("must_remove", [])
    if "must_remove" in delivery:
        _require_string_list(must_remove, "delivery.must_remove")
        for index, item in enumerate(must_remove):
            _require_exact_relative_path(item, f"must_remove[{index}]")
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

    baseline = state.get("baseline")
    if baseline is None:
        return
    if not isinstance(baseline, dict):
        raise ConfigError("baseline must be an object")
    preexisting = baseline.get("preexisting", {})
    if preexisting is not None and not isinstance(preexisting, dict):
        raise ConfigError("baseline.preexisting must be an object")


def _run_git(root: Path, arguments: list[str]) -> list[str]:
    result = subprocess_run_git(root, arguments)
    if result.returncode != 0:
        message = result.stderr.decode("utf-8", errors="replace").strip()
        raise ConfigError(message or f"git command failed: {' '.join(arguments)}")
    return [
        item.decode("utf-8", errors="surrogateescape")
        for item in result.stdout.split(b"\0")
        if item
    ]


def subprocess_run_git(root: Path, arguments: list[str]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", "-C", str(root), *arguments],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def _is_git_worktree(root: Path) -> bool:
    result = subprocess_run_git(root, ["rev-parse", "--is-inside-work-tree"])
    return result.returncode == 0


def _git_head(root: Path) -> str | None:
    result = subprocess_run_git(root, ["rev-parse", "HEAD"])
    if result.returncode != 0:
        return None
    head = result.stdout.decode("utf-8", errors="replace").strip()
    return head or None


def _parse_name_status(fields: list[str]) -> tuple[set[str], set[str]]:
    changed: set[str] = set()
    deleted: set[str] = set()
    index = 0
    while index < len(fields):
        status = fields[index]
        index += 1
        if not status:
            continue
        code = status[0]
        if code in {"R", "C"}:
            if index + 1 >= len(fields):
                break
            old_path = _norm_rel(fields[index])
            new_path = _norm_rel(fields[index + 1])
            index += 2
            if code == "R" and old_path:
                deleted.add(old_path)
            if new_path:
                changed.add(new_path)
        else:
            if index >= len(fields):
                break
            path = _norm_rel(fields[index])
            index += 1
            if not path:
                continue
            if code == "D":
                deleted.add(path)
            else:
                changed.add(path)
    return changed, deleted


def _git_name_status(root: Path, extra: list[str]) -> tuple[set[str], set[str]]:
    return _parse_name_status(_run_git(root, ["diff", "--name-status", "-z", *extra]))


def _git_untracked(root: Path) -> set[str]:
    return {_norm_rel(path) for path in _run_git(root, ["ls-files", "--others", "--exclude-standard", "-z"])}


def _git_changes_against_commit(root: Path, commit: str) -> tuple[set[str], set[str]]:
    changed: set[str] = set()
    deleted: set[str] = set()
    for extra in ([commit], ["--cached", commit]):
        current_changed, current_deleted = _git_name_status(root, extra)
        changed.update(current_changed)
        deleted.update(current_deleted)
    changed.update(_git_untracked(root))
    for path in list(deleted):
        if _lexists(_join_under_root(root, path)):
            deleted.discard(path)
            changed.add(path)
    changed.difference_update(deleted)
    return changed, deleted


def _iter_worktree_files(root: Path) -> list[str]:
    found: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [
            name for name in dirnames if not Path(dirpath, name).is_symlink()
        ]
        for name in filenames:
            path = Path(dirpath, name)
            try:
                relative = path.relative_to(root).as_posix()
            except ValueError:
                continue
            found.append(relative)
    return sorted(found)


def discover_paths(root: Path, mode: str, explicit_paths: Iterable[str]) -> list[str]:
    explicit = list(explicit_paths)
    if explicit:
        return sorted({_normalize_user_path(root, raw_path) for raw_path in explicit})

    if mode == "all":
        return _iter_worktree_files(root)

    if not _is_git_worktree(root):
        raise ConfigError("root is not a Git worktree; pass explicit paths or use --mode all")

    changed: set[str] = set()
    deleted: set[str] = set()
    if mode == "staged":
        current_changed, current_deleted = _git_name_status(root, ["--cached"])
        changed.update(current_changed)
        deleted.update(current_deleted)
    else:
        unstaged_changed, unstaged_deleted = _git_name_status(root, [])
        staged_changed, staged_deleted = _git_name_status(root, ["--cached"])
        changed.update(unstaged_changed)
        changed.update(staged_changed)
        changed.update(_git_untracked(root))
        deleted.update(unstaged_deleted)
        deleted.update(staged_deleted)
    return sorted(changed | deleted)


def _hash_nofollow(path: Path) -> str:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags)
    try:
        digest = hashlib.sha256()
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
        return digest.hexdigest()
    finally:
        os.close(fd)


def _snapshot_path(root: Path, relative: str) -> dict[str, Any]:
    if _symlinked_ancestor(root, relative) is not None:
        return {"kind": "blocked"}
    path = _join_under_root(root, relative)
    info = _lstat(path)
    if info is None:
        return {"kind": "missing"}
    if stat.S_ISLNK(info.st_mode):
        target = os.fsencode(os.readlink(path))
        return {"kind": "symlink", "digest": hashlib.sha256(target).hexdigest()}
    if stat.S_ISREG(info.st_mode):
        return {"kind": "file", "digest": _hash_nofollow(path)}
    if stat.S_ISDIR(info.st_mode):
        return {"kind": "dir"}
    return {"kind": "other"}


def capture_baseline(root: Path) -> dict[str, Any]:
    preexisting: dict[str, Any] = {}
    git_head = None
    coverage = "limited"
    if _is_git_worktree(root):
        git_head = _git_head(root)
        try:
            if git_head:
                changed, deleted = _git_changes_against_commit(root, git_head)
            else:
                changed, deleted = _git_untracked(root), set()
            for relative in sorted(changed | deleted):
                preexisting[relative] = _snapshot_path(root, relative)
            if git_head:
                coverage = "git"
        except (ConfigError, OSError):
            preexisting = {}
            coverage = "limited"
    return {
        "root": str(root.resolve()),
        "git_head": git_head,
        "coverage": coverage,
        "preexisting": preexisting,
    }


def _baseline_root_conflict(baseline: Any, root: Path) -> str | None:
    if baseline is None:
        return None
    if not isinstance(baseline, dict):
        return "baseline must be an object"
    recorded = baseline.get("root")
    if not recorded:
        return None
    try:
        recorded_root = Path(str(recorded)).resolve()
    except OSError:
        return "existing state baseline root is invalid"
    if recorded_root != root.resolve():
        return "existing state belongs to a different root"
    return None


def _complete_git_baseline(state: dict[str, Any], root: Path) -> dict[str, Any] | None:
    baseline = state.get("baseline")
    if not isinstance(baseline, dict):
        return None
    if _baseline_root_conflict(baseline, root):
        return None
    if baseline.get("coverage") != "git":
        return None
    git_head = baseline.get("git_head")
    if not isinstance(git_head, str) or not git_head.strip():
        return None
    preexisting = baseline.get("preexisting", {})
    if preexisting is not None and not isinstance(preexisting, dict):
        return None
    return baseline


def classify_changes(
    root: Path, state: dict[str, Any], discovered: Iterable[str]
) -> tuple[list[str], list[str], str, str]:
    discovered_paths = [_norm_rel(path) for path in discovered]
    baseline = _complete_git_baseline(state, root)
    if baseline is None:
        changed: list[str] = []
        deleted: list[str] = []
        for relative in discovered_paths:
            path = _join_under_root(root, relative)
            if _lexists(path):
                changed.append(relative)
            else:
                deleted.append(relative)
        return (
            changed,
            deleted,
            "limited",
            "No complete start baseline; this check does not verify that original user changes were left untouched.",
        )

    git_head = str(baseline["git_head"])
    result = subprocess_run_git(root, ["cat-file", "-e", f"{git_head}^{{commit}}"])
    if result.returncode != 0:
        raise ConfigError("task baseline commit is unavailable; refusing to use incomplete coverage as complete")

    preexisting = baseline.get("preexisting") or {}
    current_changed, current_deleted = _git_changes_against_commit(root, git_head)
    this_round_changed: set[str] = set()
    this_round_deleted: set[str] = set()

    for relative in current_changed:
        old = preexisting.get(relative)
        now = _snapshot_path(root, relative)
        if (
            isinstance(old, dict)
            and old.get("kind") == now.get("kind")
            and old.get("digest") == now.get("digest")
            and now.get("kind") != "missing"
        ):
            continue
        if now.get("kind") == "missing":
            this_round_deleted.add(relative)
        else:
            this_round_changed.add(relative)

    for relative in current_deleted:
        old = preexisting.get(relative)
        if isinstance(old, dict) and old.get("kind") == "missing":
            continue
        this_round_deleted.add(relative)

    for relative, old in preexisting.items():
        if not isinstance(old, dict):
            continue
        now = _snapshot_path(root, relative)
        if old.get("kind") == "missing":
            if now.get("kind") != "missing":
                this_round_changed.add(relative)
            continue
        if now.get("kind") == "missing":
            this_round_deleted.add(relative)
        elif old.get("kind") != now.get("kind") or old.get("digest") != now.get("digest"):
            this_round_changed.add(relative)

    this_round_changed.difference_update(this_round_deleted)
    return (
        sorted(this_round_changed),
        sorted(this_round_deleted),
        "git-baseline",
        "This-round file operations are compared against the task-start Git baseline.",
    )


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


def _must_remove_paths(state: dict[str, Any]) -> list[str]:
    values = state.get("delivery", {}).get("must_remove", [])
    if not isinstance(values, list):
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for item in values:
        if not isinstance(item, str) or not item.strip():
            continue
        path = _norm_rel(item)
        if path in seen:
            continue
        seen.add(path)
        normalized.append(path)
    return normalized


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


def _inspect_existing_file(
    root: Path,
    state: dict[str, Any],
    relative_path: str,
    retired_terms: list[str],
    leak_markers: list[str],
    process_trace_allowlist: list[str],
    seen: set[tuple[str, str, int | None, str | None]],
) -> tuple[list[Violation], bool]:
    violations: list[Violation] = []
    if _symlinked_ancestor(root, relative_path) is not None:
        violations.append(
            Violation(
                "STC004",
                relative_path,
                "cannot inspect a path that traverses a symbolic link",
            )
        )
        return violations, False
    artifact = _join_under_root(root, relative_path)
    info = _lstat(artifact)
    if info is None or stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        return violations, False

    try:
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(artifact, flags)
        try:
            raw = os.read(fd, MAX_TEXT_BYTES + 1)
        finally:
            os.close(fd)
    except OSError as exc:
        violations.append(Violation("STC004", relative_path, f"cannot read artifact: {exc}"))
        return violations, True
    if len(raw) > MAX_TEXT_BYTES:
        violations.append(
            Violation("STC004", relative_path, f"artifact exceeds {MAX_TEXT_BYTES} bytes")
        )
        return violations, True
    if b"\0" in raw[:8192]:
        return violations, True
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        violations.append(Violation("STC004", relative_path, "artifact is not UTF-8 text"))
        return violations, True

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
        return violations, True
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
    return violations, True


def check_artifacts(
    root: Path, state_path: Path, state: dict[str, Any], paths: Iterable[str]
) -> tuple[list[Violation], int, str, str]:
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
    must_remove = _must_remove_paths(state)
    must_remove_set = set(must_remove)

    changed, deleted, coverage, coverage_note = classify_changes(root, state, paths)
    seen: set[tuple[str, str, int | None, str | None]] = set()
    this_round_changed: list[str] = []
    seen_changed: set[str] = set()
    for relative_path in changed:
        relative_path = _norm_rel(relative_path)
        if not relative_path or relative_path in seen_changed:
            continue
        seen_changed.add(relative_path)
        if _is_ignored(relative_path, state, state_path, root):
            continue
        this_round_changed.append(relative_path)
        if not _mapped_requirements(relative_path, state):
            violations.append(
                Violation("STC002", relative_path, "changed artifact maps to no active requirement")
            )

    inspect_paths: list[str] = []
    seen_inspect: set[str] = set()
    for relative_path in [*this_round_changed, *paths]:
        relative_path = _norm_rel(relative_path)
        if not relative_path or relative_path in seen_inspect:
            continue
        seen_inspect.add(relative_path)
        if _is_ignored(relative_path, state, state_path, root):
            continue
        inspect_paths.append(relative_path)

    for relative_path in inspect_paths:
        content_violations, inspected = _inspect_existing_file(
            root,
            state,
            relative_path,
            retired_terms,
            leak_markers,
            process_trace_allowlist,
            seen,
        )
        violations.extend(content_violations)
        if inspected:
            checked += 1

    for relative_path in deleted:
        relative_path = _norm_rel(relative_path)
        if _is_ignored(relative_path, state, state_path, root):
            continue
        if relative_path in must_remove_set:
            continue
        violations.append(
            Violation(
                "STC005",
                relative_path,
                "file deleted without authorization",
            )
        )

    for relative_path in must_remove:
        artifact = _join_under_root(root, relative_path)
        if _lexists(artifact):
            violations.append(
                Violation(
                    "STC006",
                    relative_path,
                    "required removal still exists",
                )
            )

    return violations, checked, coverage, coverage_note


def _existing_state_reuse_error(state_path: Path, root: Path) -> str | None:
    try:
        raw = json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return f"existing state is not valid JSON: {exc}"
    except OSError as exc:
        return f"existing state could not be read: {exc}"
    if not isinstance(raw, dict):
        return "existing state root must be an object"
    if raw.get("schema_version") != SCHEMA_VERSION:
        return f"existing state schema_version must be {SCHEMA_VERSION}"
    target = raw.get("active_target")
    if not isinstance(target, dict):
        return "existing state active_target must be an object"
    conflict = _baseline_root_conflict(raw.get("baseline"), root)
    if conflict:
        return conflict
    return None


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
        if not state_path.is_file():
            raise ConfigError(f"existing state is not a file: {state_path}")
        error = _existing_state_reuse_error(state_path, root)
        if error:
            raise ConfigError(f"{error}; refusing to reuse or overwrite {state_path}")
        print(f"Reusing existing transient state: {state_path}")
        print("Start baseline was not reset.")
        try:
            existing = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            existing = {}
        if not isinstance(existing, dict) or existing.get("ready") is not True:
            print("Replace template values before running check.")
        return 0
    state_dir.mkdir(parents=True, exist_ok=True)
    try:
        template = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"state template is not valid JSON: {exc}") from exc
    if not isinstance(template, dict):
        raise ConfigError("state template root must be an object")
    template["baseline"] = capture_baseline(root)
    state_path.write_text(json.dumps(template, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
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
    conflict = _baseline_root_conflict(state.get("baseline"), root)
    if conflict:
        raise ConfigError(conflict)
    paths = discover_paths(root, args.mode, args.paths)
    violations, checked, coverage, coverage_note = check_artifacts(
        root, state_path, state, paths
    )
    state_removed = False
    if not violations and args.cleanup_state_on_pass:
        try:
            state_path.unlink()
        except OSError as exc:
            raise ConfigError(f"check passed but transient state could not be removed: {exc}") from exc
        state_removed = True
    payload = {
        "ok": not violations,
        "checked_files": checked,
        "coverage": coverage,
        "coverage_note": coverage_note,
        "state_removed": state_removed,
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
        if coverage == "limited":
            print(coverage_note)
    else:
        suffix = "; transient state removed" if state_removed else ""
        coverage_suffix = ""
        if coverage == "limited":
            coverage_suffix = "; coverage is limited and does not verify original user changes were left untouched"
        print(
            f"PASS Stop Chatter: configured checks passed for {checked} artifact(s)"
            f"{suffix}{coverage_suffix}"
        )
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
    check_parser.add_argument(
        "--cleanup-state-on-pass",
        action="store_true",
        help="remove only the transient state file after a successful check",
    )
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
