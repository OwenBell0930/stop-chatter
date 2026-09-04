#!/usr/bin/env python3
"""Reproducible end-to-end benchmark for correction-residue behavior."""

from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import hashlib
import importlib.util
import json
import math
import os
import platform
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
CASES_ROOT = Path(__file__).resolve().parent / "cases"
GATE_CORPUS = Path(__file__).resolve().parent / "gate_corpus.json"
GATE = REPO_ROOT / "scripts" / "stop_chatter.py"
INSTALLER = REPO_ROOT / "scripts" / "install.py"
DEFAULT_GROK_BIN = Path(
    "/Applications/Grok Build.app/Contents/Resources/resources/bin/grok"
)
DEFAULT_CODEBUDDY_BIN = Path(
    "/Applications/WorkBuddy.app/Contents/Resources/app.asar.unpacked/cli/bin/codebuddy"
)
WORKBUDDY_MODELS_PATH = Path.home() / ".workbuddy" / "models.json"
CODEBUDDY_EVAL_TOOLS = "Bash,Read,Write,Edit,Glob,Grep,Skill"
CHECKER_WRAPPER = '''#!/usr/bin/env python3
import json
import subprocess
import sys
import time
from pathlib import Path

impl = Path(__file__).resolve().parent / "stop_chatter.impl.py"
log = Path(".stop-chatter") / "tool-log.jsonl"
log.parent.mkdir(parents=True, exist_ok=True)
turn = "unknown"
marker = Path(".stop-chatter") / "eval-turn"
if marker.is_file():
    turn = marker.read_text(encoding="utf-8").strip() or "unknown"
started = time.monotonic()
proc = subprocess.run(
    [sys.executable, str(impl), *sys.argv[1:]],
    capture_output=True,
)
if proc.stdout:
    sys.stdout.buffer.write(proc.stdout)
if proc.stderr:
    sys.stderr.buffer.write(proc.stderr)
argv = sys.argv[1:]
command = "other"
if "init" in argv:
    command = "init"
elif "check" in argv:
    command = "check"
payload = {
    "kind": "checker",
    "turn": turn,
    "command": command,
    "argv": argv,
    "exit_code": proc.returncode,
    "duration_ms": int((time.monotonic() - started) * 1000),
}
if proc.returncode != 0:
    err = (proc.stderr or proc.stdout or b"").decode("utf-8", "replace")[-500:]
    payload["failure_reason"] = err
log.open("a", encoding="utf-8").write(json.dumps(payload, ensure_ascii=False) + "\\n")
raise SystemExit(proc.returncode)
'''
USAGE_KEYS = ("input_tokens", "cached_input_tokens", "output_tokens")
EMPTY_USAGE = {key: None for key in USAGE_KEYS}
LEFTOVER_COMMIT = "补进上一轮超范围草稿留下的额外材料"
PRODUCT_COMMIT = "当前产品初稿"
BENCHMARK_VERSION = "sce-1.2"
IGNORED_PREFIXES = (
    ".git/",
    ".agents/",
    ".claude/",
    ".codebuddy/",
    ".stop-chatter/",
    "__pycache__/",
)
CACHE_DIRECTORY_NAMES = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
KNOWN_CODES = ("STC001", "STC002", "STC003", "STC004")
CONDITION_ORDER = ("baseline", "light", "guarded")


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def run_command(
    command: list[str],
    *,
    cwd: Path | None = None,
    timeout: int = 300,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=timeout,
    )


def path_matches(path: str, pattern: str) -> bool:
    normalized_path = PurePosixPath(path).as_posix().lstrip("./")
    normalized_pattern = PurePosixPath(pattern).as_posix().lstrip("./")
    if normalized_pattern.endswith("/**"):
        prefix = normalized_pattern[:-3].rstrip("/")
        if normalized_path == prefix or normalized_path.startswith(prefix + "/"):
            return True
    return fnmatch.fnmatchcase(normalized_path, normalized_pattern)


def ignored_artifact(path: str) -> bool:
    normalized = PurePosixPath(path).as_posix()
    while normalized.startswith("./"):
        normalized = normalized[2:]
    normalized = normalized.lstrip("/")
    parts = PurePosixPath(normalized).parts
    return (
        normalized == ".git"
        or any(part in CACHE_DIRECTORY_NAMES for part in parts)
        or any(normalized.startswith(prefix) for prefix in IGNORED_PREFIXES)
    )


def snapshot(root: Path) -> dict[str, bytes]:
    result: dict[str, bytes] = {}
    for path in root.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(root).as_posix()
        if ignored_artifact(relative):
            continue
        result[relative] = path.read_bytes()
    return result


def changed_paths(before: dict[str, bytes], after: dict[str, bytes]) -> list[str]:
    return sorted(
        path
        for path in set(before) | set(after)
        if before.get(path) != after.get(path)
    )


def load_cases(selected: Iterable[str] | None = None) -> list[dict[str, Any]]:
    wanted = set(selected or [])
    cases: list[dict[str, Any]] = []
    for spec_path in sorted(CASES_ROOT.glob("*/case.json")):
        case = json.loads(spec_path.read_text(encoding="utf-8"))
        if wanted and case["id"] not in wanted:
            continue
        case["_directory"] = str(spec_path.parent)
        cases.append(case)
    if wanted:
        found = {case["id"] for case in cases}
        missing = sorted(wanted - found)
        if missing:
            raise ValueError(f"unknown case(s): {', '.join(missing)}")
    if not cases:
        raise ValueError("no benchmark cases selected")
    return cases


def requirement_failures(files: dict[str, bytes], requirements: list[dict[str, Any]]) -> list[str]:
    failures: list[str] = []
    for requirement in requirements:
        path = requirement["path"]
        raw = files.get(path)
        if raw is None:
            failures.append(f"missing required path: {path}")
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            failures.append(f"required path is not UTF-8: {path}")
            continue
        for needle in requirement.get("contains", []):
            if needle not in text:
                failures.append(f"{path} missing text: {needle}")
        for pattern in requirement.get("regex", []):
            if re.search(pattern, text, flags=re.MULTILINE | re.DOTALL) is None:
                failures.append(f"{path} missing pattern: {pattern}")
    return failures


def scan_pattern_hits(
    files: dict[str, bytes], patterns: list[str]
) -> list[dict[str, str]]:
    artifact_hits: list[dict[str, str]] = []
    compiled = [(pattern, re.compile(pattern, flags=re.IGNORECASE | re.MULTILINE)) for pattern in patterns]
    for path, raw in sorted(files.items()):
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        for source, pattern in compiled:
            match = pattern.search(text)
            if match:
                artifact_hits.append({"path": path, "pattern": source, "match": match.group(0)[:120]})
    return artifact_hits


def run_hidden_check(root: Path, case: dict[str, Any]) -> tuple[bool, str]:
    command = case.get("hidden_check")
    if not command:
        return True, ""
    result = run_command(command, cwd=root, timeout=60)
    output = (result.stdout + result.stderr).strip()
    return result.returncode == 0, output[-1000:]


def score_workspace(
    root: Path,
    before: dict[str, bytes],
    case: dict[str, Any],
    *,
    continuation: bool,
) -> dict[str, Any]:
    files = snapshot(root)
    changed = changed_paths(before, files)
    requirements = list(case.get("requirements", []))
    if continuation:
        requirements.extend(case.get("continuation_requirements", []))
    required_failures = requirement_failures(files, requirements)

    retired_artifact = scan_pattern_hits(files, case.get("retired_patterns", []))
    trace_artifact = scan_pattern_hits(files, case.get("process_trace_patterns", []))

    unexpected_changes = [
        path
        for path in changed
        if not any(path_matches(path, pattern) for pattern in case.get("allowed_changed_paths", []))
    ]
    forbidden_paths_present = [
        path
        for pattern in case.get("forbidden_paths", [])
        for path in files
        if path_matches(path, pattern)
    ]
    protected_failures = [
        path
        for path in case.get("protected_paths", [])
        if before.get(path) != files.get(path)
    ]
    hidden_ok, hidden_output = run_hidden_check(root, case)
    transient_state_clean = not (root / ".stop-chatter" / "state.json").exists()
    retired_surface_removed = not forbidden_paths_present
    no_unrelated_mutation = not unexpected_changes and not protected_failures

    metrics = {
        "active_requirements_preserved": not required_failures,
        "artifact_residue_free": not retired_artifact,
        "process_trace_artifact_free": not trace_artifact,
        "retired_surface_removed": retired_surface_removed,
        "no_unrelated_mutation": no_unrelated_mutation,
        "scope_clean": retired_surface_removed and no_unrelated_mutation,
        "hidden_check_passed": hidden_ok,
        "transient_state_clean": transient_state_clean,
    }
    artifact_success = all(
        metrics[key]
        for key in (
            "active_requirements_preserved",
            "artifact_residue_free",
            "process_trace_artifact_free",
            "retired_surface_removed",
            "no_unrelated_mutation",
            "hidden_check_passed",
        )
    )
    return {
        "artifact_success": artifact_success,
        "metrics": metrics,
        "changed_paths": changed,
        "required_failures": required_failures,
        "retired_artifact_hits": retired_artifact,
        "process_trace_artifact_hits": trace_artifact,
        "unexpected_changes": unexpected_changes,
        "forbidden_paths_present": sorted(set(forbidden_paths_present)),
        "protected_failures": protected_failures,
        "hidden_check_output": hidden_output,
        "artifact_sha256": sha256_bytes(
            b"".join(path.encode("utf-8") + b"\0" + files[path] + b"\0" for path in sorted(files))
        ),
    }


def _git(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    result = run_command(["git", *arguments], cwd=root, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"command failed: git {' '.join(arguments)}")
    return result


def leftover_fixture_paths(root: Path, case: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    for relative in case.get("forbidden_paths", []):
        path = root / relative
        if path.is_file():
            paths.append(relative)
    return paths


def init_git(root: Path, leftover_paths: list[str] | None = None) -> None:
    leftovers = leftover_paths or []
    saved: dict[str, bytes] = {}
    for relative in leftovers:
        path = root / relative
        saved[relative] = path.read_bytes()
        path.unlink()
        current = path.parent
        while current != root and current.is_dir() and not any(current.iterdir()):
            current.rmdir()
            current = current.parent
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "chatterbench@example.invalid")
    _git(root, "config", "user.name", "ChatterBench")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", PRODUCT_COMMIT)
    if saved:
        for relative, data in saved.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        _git(root, "add", "-A")
        _git(root, "commit", "-qm", LEFTOVER_COMMIT)


def prepare_workspace(case: dict[str, Any], destination: Path, condition: str) -> dict[str, bytes]:
    fixture = Path(case["_directory"]) / "fixture"
    shutil.copytree(fixture, destination)
    init_git(destination, leftover_fixture_paths(destination, case))
    before = snapshot(destination)
    exclude = destination / ".git" / "info" / "exclude"
    with exclude.open("a", encoding="utf-8") as handle:
        handle.write("\n__pycache__/\n**/__pycache__/\n.pytest_cache/\n")
    if condition in {"light", "guarded"}:
        result = run_command(
            [
                sys.executable,
                str(INSTALLER),
                "--host",
                "cursor",
                "--scope",
                "project",
                "--target",
                str(destination),
            ],
            timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip())
        with exclude.open("a", encoding="utf-8") as handle:
            handle.write("\n.agents/\n.grok/\n.codebuddy/\n.stop-chatter/\n")
        wrap_checker(destination)
        install_codebuddy_skill_copy(destination)
    return before


def install_codebuddy_skill_copy(root: Path) -> None:
    source = root / ".agents" / "skills" / "stop-chatter"
    if not source.is_dir():
        raise RuntimeError(f"installed skill not found: {source}")
    target = root / ".codebuddy" / "skills" / "stop-chatter"
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target)


def set_eval_turn(root: Path, turn: str) -> None:
    marker = root / ".stop-chatter" / "eval-turn"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(turn + "\n", encoding="utf-8")


def wrap_checker(root: Path) -> None:
    script = root / ".agents" / "skills" / "stop-chatter" / "scripts" / "stop_chatter.py"
    if not script.is_file():
        raise RuntimeError(f"installed checker not found: {script}")
    impl = script.with_name("stop_chatter.impl.py")
    if not impl.exists():
        script.replace(impl)
    script.write_text(CHECKER_WRAPPER, encoding="utf-8")
    script.chmod(impl.stat().st_mode)


def save_artifact_tree(source: Path, destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)
    for path in source.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(source).as_posix()
        if ignored_artifact(relative):
            continue
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)


def read_tool_journal(root: Path) -> dict[str, Any]:
    path = root / ".stop-chatter" / "tool-log.jsonl"
    events: list[dict[str, Any]] = []
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                events.append(json.loads(line))
    counts = {"checker_init": 0, "checker_check": 0, "checker_cleanup_flag": 0}
    for event in events:
        argv = [str(item) for item in event.get("argv", [])]
        if "init" in argv:
            counts["checker_init"] += 1
        if "check" in argv:
            counts["checker_check"] += 1
            if "--cleanup-state-on-pass" in argv:
                counts["checker_cleanup_flag"] += 1
    return {"events": events, "counts": counts}


def make_guard_state(case: dict[str, Any]) -> dict[str, Any]:
    """Shape helper for unit tests. Campaign workspaces must not be pre-seeded."""
    guard = case["guard"]
    return {
        "schema_version": 1,
        "ready": True,
        "active_target": {
            "goal": case["goal"],
            "requirements": [
                {
                    "id": "R1",
                    "text": case["goal"],
                    "paths": guard["requirement_paths"],
                }
            ],
            "meta_constraints": [
                {
                    "id": "M1",
                    "text": "Keep the execution concise; do not turn it into artifact copy.",
                    "leak_markers": guard.get("meta_markers", []),
                }
            ],
        },
        "retired": [
            {
                "id": f"X{index}",
                "label": item["label"],
                "aliases": item.get("aliases", []),
                "scope": "task",
            }
            for index, item in enumerate(guard.get("retired", []), start=1)
        ],
        "delivery": {
            "ignore_paths": [".git/**", ".agents/**", ".stop-chatter/**", "__pycache__/**"],
            "allow_process_trace_paths": [],
            "exceptions": guard.get("exceptions", []),
        },
    }


def condition_prompt(condition: str, case: dict[str, Any]) -> str:
    prompt = case["prompt"]
    if condition == "baseline":
        return prompt
    if condition == "light":
        return "Use the stop-chatter skill in Light mode for this task.\n\n" + prompt
    if condition == "guarded":
        return "Use the stop-chatter skill in Guarded mode for this task.\n\n" + prompt
    raise ValueError(f"unknown condition: {condition}")


def schedule_conditions(conditions: list[str], repeat: int, case_index: int) -> list[str]:
    if not conditions:
        return []
    shift = (repeat - 1 + case_index) % len(conditions)
    return conditions[shift:] + conditions[:shift]


def run_cost_usd(record: dict[str, Any]) -> float | None:
    values: list[float] = []
    for key in ("correction_turn", "continuation_turn"):
        raw = record.get(key, {}).get("cost_usd")
        if raw is None:
            return None
        values.append(float(raw))
    return sum(values)


def parse_codex_events(stdout: str) -> dict[str, Any]:
    session_id = ""
    usage = {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0}
    event_types: list[str] = []
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        event_type = str(event.get("type", ""))
        if event_type:
            event_types.append(event_type)
        if event_type == "thread.started":
            session_id = str(event.get("thread_id", ""))
        if event_type == "turn.completed":
            raw_usage = event.get("usage", {})
            for key in usage:
                value = raw_usage.get(key, 0)
                if isinstance(value, int):
                    usage[key] += value
    return {
        "session_id": session_id,
        "usage": usage,
        "event_types": sorted(set(event_types)),
    }


def build_codex_command(
    *,
    codex_bin: str,
    prompt: str,
    model: str,
    reasoning: str,
    cwd: Path | None = None,
    session_id: str | None = None,
) -> list[str]:
    turn_options = [
        "--json",
        "--ignore-user-config",
        "--ignore-rules",
        "--model",
        model,
        "-c",
        f'model_reasoning_effort="{reasoning}"',
        "-c",
        'approval_policy="never"',
    ]
    if session_id:
        if cwd is None:
            raise ValueError("cwd is required when resuming a turn")
        # --color belongs to `exec`, not to the packaged CLI's `resume` subcommand.
        # The packaged CLI does not inherit cwd/sandbox from the first turn, so
        # both exec-level options must be supplied again before `resume`.
        return [
            codex_bin,
            "exec",
            "--color",
            "never",
            "--sandbox",
            "workspace-write",
            "--cd",
            str(cwd),
            "resume",
            *turn_options,
            session_id,
            prompt,
        ]
    if cwd is None:
        raise ValueError("cwd is required for the first turn")
    return [
        codex_bin,
        "exec",
        *turn_options,
        "--color",
        "never",
        "--sandbox",
        "workspace-write",
        "--cd",
        str(cwd),
        prompt,
    ]


def codex_turn(
    *,
    codex_bin: str,
    prompt: str,
    model: str,
    reasoning: str,
    timeout: int,
    cwd: Path | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    command = build_codex_command(
        codex_bin=codex_bin,
        prompt=prompt,
        model=model,
        reasoning=reasoning,
        cwd=cwd,
        session_id=session_id,
    )
    started = time.monotonic()
    try:
        result = run_command(command, timeout=timeout)
        parsed = parse_codex_events(result.stdout)
        parsed.update(
            {
                "ok": result.returncode == 0,
                "returncode": result.returncode,
                "duration_seconds": round(time.monotonic() - started, 3),
                "error": (result.stderr or "")[-1000:] if result.returncode else "",
            }
        )
        return parsed
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "returncode": 124,
            "duration_seconds": round(time.monotonic() - started, 3),
            "error": f"timeout after {timeout}s",
            "session_id": "",
            "usage": {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0},
            "event_types": [],
        }


def artifact_patch(root: Path) -> str:
    tracked = run_command(["git", "diff", "--no-ext-diff", "--binary", "HEAD"], cwd=root, timeout=30)
    text = tracked.stdout
    untracked = run_command(
        ["git", "ls-files", "--others", "--exclude-standard", "-z"], cwd=root, timeout=30
    )
    for relative in [item for item in untracked.stdout.split("\0") if item]:
        if ignored_artifact(relative):
            continue
        path = root / relative
        if not path.is_file() or path.is_symlink():
            continue
        raw = path.read_bytes()
        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError:
            content = f"<binary sha256={sha256_bytes(raw)}>\n"
        text += f"\n--- /dev/null\n+++ b/{relative}\n@@ new file @@\n{content}"
        if content and not content.endswith("\n"):
            text += "\n"
    return text


def optional_int(value: Any) -> int | None:
    if value is None or value is False or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def optional_float(value: Any) -> float | None:
    if value is None or value is False or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def public_usage(usage: Any) -> dict[str, int | None]:
    raw = usage if isinstance(usage, dict) else {}
    return {key: optional_int(raw.get(key)) for key in USAGE_KEYS}


def merge_usage(*usages: Any) -> dict[str, int | None]:
    result: dict[str, int | None] = {}
    for key in USAGE_KEYS:
        values = [public_usage(item).get(key) for item in usages]
        if any(value is None for value in values):
            result[key] = None
        else:
            result[key] = sum(int(value) for value in values)
    return result


def merge_optional_numbers(*values: Any) -> float | None:
    parsed = [optional_float(value) for value in values]
    if any(value is None for value in parsed):
        return None
    return round(sum(parsed), 6)


def parse_usage_fields(raw_usage: Any) -> dict[str, int | None]:
    if not isinstance(raw_usage, dict) or not raw_usage:
        return dict(EMPTY_USAGE)
    mapping = {
        "input_tokens": ("input_tokens",),
        "cached_input_tokens": ("cache_read_input_tokens", "cached_input_tokens"),
        "output_tokens": ("output_tokens",),
    }
    parsed: dict[str, int | None] = {}
    for target, names in mapping.items():
        found = None
        for name in names:
            if name in raw_usage and raw_usage[name] is not None:
                found = optional_int(raw_usage[name])
                break
        parsed[target] = found
    return parsed


def public_turn(turn: dict[str, Any]) -> dict[str, Any]:
    cost = optional_float(turn.get("cost_usd"))
    return {
        "ok": bool(turn.get("ok")),
        "returncode": turn.get("returncode"),
        "duration_seconds": optional_float(turn.get("duration_seconds")),
        "usage": public_usage(turn.get("usage")),
        "event_types": list(turn.get("event_types") or []),
        "error": turn.get("error") or "",
        "model_slug": turn.get("model_slug") or "",
        "cost_usd": cost,
        "cost_usd_estimated": True if cost is not None else None,
        "num_turns": optional_int(turn.get("num_turns")),
        "stop_reason": turn.get("stop_reason") or "",
    }


def grok_version(grok_bin: str) -> str:
    result = run_command([grok_bin, "--version"], timeout=30)
    return result.stdout.strip() if result.returncode == 0 else "unavailable"


def parse_grok_payload(stdout: str) -> dict[str, Any]:
    text = stdout.strip()
    if not text:
        return {}
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            return {}
        try:
            payload = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return {}
    if not isinstance(payload, dict):
        return {}
    raw_usage = payload.get("usage")
    usage = parse_usage_fields(raw_usage)
    model_usage = payload.get("modelUsage") or {}
    model_slug = ""
    if isinstance(model_usage, dict) and model_usage:
        model_slug = str(next(iter(model_usage)))
    elif payload.get("model"):
        model_slug = str(payload.get("model"))
    return {
        "session_id": str(payload.get("sessionId") or ""),
        "usage": usage,
        "stop_reason": str(payload.get("stopReason") or payload.get("stop_reason") or ""),
        "model_slug": model_slug,
        "cost_usd": optional_float(payload.get("total_cost_usd")),
        "num_turns": optional_int(payload.get("num_turns")),
    }


def build_grok_command(
    *,
    grok_bin: str,
    prompt: str,
    model: str,
    reasoning: str,
    cwd: Path,
    session_id: str | None = None,
) -> list[str]:
    command = [
        grok_bin,
        "--cwd",
        str(cwd),
        "-m",
        model,
        "--output-format",
        "json",
        "--always-approve",
        "--disable-web-search",
        "--no-subagents",
        "--no-memory",
        "--verbatim",
        "--effort",
        reasoning,
        "-p",
        prompt,
    ]
    if session_id:
        command.extend(["--resume", session_id])
    return command


def grok_turn(
    *,
    grok_bin: str,
    prompt: str,
    model: str,
    reasoning: str,
    timeout: int,
    cwd: Path,
    session_id: str | None = None,
) -> dict[str, Any]:
    command = build_grok_command(
        grok_bin=grok_bin,
        prompt=prompt,
        model=model,
        reasoning=reasoning,
        cwd=cwd,
        session_id=session_id,
    )
    env = os.environ.copy()
    env["GROK_CURSOR_SKILLS_ENABLED"] = "false"
    env["GROK_CLAUDE_SKILLS_ENABLED"] = "false"
    env["GROK_CODEX_SKILLS_ENABLED"] = "false"
    started = time.monotonic()
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=timeout,
            env=env,
        )
        parsed = parse_grok_payload(result.stdout)
        return {
            "ok": result.returncode == 0,
            "returncode": result.returncode,
            "duration_seconds": round(time.monotonic() - started, 3),
            "error": (result.stderr or "")[-1000:] if result.returncode else "",
            "session_id": parsed.get("session_id") or "",
            "usage": parsed.get("usage") or dict(EMPTY_USAGE),
            "event_types": ["grok.headless"],
            "model_slug": parsed.get("model_slug") or "",
            "cost_usd": parsed.get("cost_usd"),
            "stop_reason": parsed.get("stop_reason") or "",
            "num_turns": parsed.get("num_turns"),
        }
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "returncode": 124,
            "duration_seconds": round(time.monotonic() - started, 3),
            "error": f"timeout after {timeout}s",
            "session_id": "",
            "usage": dict(EMPTY_USAGE),
            "event_types": [],
            "model_slug": "",
            "cost_usd": None,
            "stop_reason": "timeout",
            "num_turns": None,
        }


def load_workbuddy_glm5_model() -> dict[str, Any]:
    if not WORKBUDDY_MODELS_PATH.is_file():
        raise RuntimeError(f"WorkBuddy models file not found: {WORKBUDDY_MODELS_PATH}")
    raw = json.loads(WORKBUDDY_MODELS_PATH.read_text(encoding="utf-8"))
    models = raw if isinstance(raw, list) else raw.get("models") if isinstance(raw, dict) else None
    if not isinstance(models, list):
        raise RuntimeError("WorkBuddy models.json has no model list")
    for item in models:
        if isinstance(item, dict) and item.get("id") == "glm-5":
            return item
    raise RuntimeError("WorkBuddy models.json has no glm-5 custom model")


def write_codebuddy_home(home: Path) -> Path:
    home.mkdir(parents=True, exist_ok=True)
    model = load_workbuddy_glm5_model()
    (home / "models.json").write_text(
        json.dumps({"models": [model]}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (home / "settings.json").write_text(
        json.dumps(
            {
                "enabledPlugins": {},
                "disableAllHooks": True,
                "sandbox": {"enabled": False},
                "memory": {
                    "autoMemoryEnabled": False,
                    "memoryExtraction": False,
                    "relevanceSelection": False,
                },
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return home


def codebuddy_version(codebuddy_bin: str) -> str:
    result = run_command([codebuddy_bin, "--version"], timeout=60)
    return result.stdout.strip() if result.returncode == 0 else "unavailable"


def parse_codebuddy_payload(stdout: str) -> dict[str, Any]:
    text = stdout.strip()
    if not text:
        return {}
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        start_obj = text.find("{")
        start_arr = text.find("[")
        starts = [index for index in (start_obj, start_arr) if index >= 0]
        if not starts:
            return {}
        start = min(starts)
        end = text.rfind("}") if text[start] == "{" else text.rfind("]")
        if end <= start:
            return {}
        try:
            payload = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return {}
    items = payload if isinstance(payload, list) else [payload] if isinstance(payload, dict) else []
    result_event: dict[str, Any] = {}
    model_slug = ""
    request_model = ""
    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "result":
            result_event = item
        provider = item.get("providerData")
        if isinstance(provider, dict):
            if provider.get("model"):
                model_slug = str(provider.get("model"))
            if provider.get("requestModelId"):
                request_model = str(provider.get("requestModelId"))
        message = item.get("message")
        if isinstance(message, dict) and message.get("model"):
            model_slug = str(message.get("model"))
    if not result_event and isinstance(payload, dict):
        result_event = payload
    cost = optional_float(result_event.get("total_cost_usd"))
    if cost == 0:
        cost = None
    subtype = str(result_event.get("subtype") or "")
    is_error = bool(result_event.get("is_error"))
    return {
        "session_id": str(result_event.get("session_id") or result_event.get("sessionId") or ""),
        "usage": parse_usage_fields(result_event.get("usage")),
        "stop_reason": subtype or ("error" if is_error else ""),
        "model_slug": model_slug or request_model,
        "cost_usd": cost,
        "num_turns": optional_int(result_event.get("num_turns")),
        "is_error": is_error,
    }


def build_codebuddy_command(
    *,
    codebuddy_bin: str,
    prompt: str,
    model: str,
    reasoning: str,
    session_id: str | None = None,
) -> list[str]:
    command = [
        codebuddy_bin,
        "-p",
        prompt,
        "--output-format",
        "json",
        "--model",
        model,
        "--effort",
        reasoning,
        "--permission-mode",
        "bypassPermissions",
        "--dangerously-skip-permissions",
        "--tools",
        CODEBUDDY_EVAL_TOOLS,
        "--disallowedTools",
        "WebFetch,WebSearch,Agent,Task,TeamCreate,ImageGen,VideoGen",
        "--strict-mcp-config",
        "--mcp-config",
        '{"mcpServers":{}}',
        "--setting-sources",
        "user,project",
        "--max-turns",
        "40",
    ]
    if session_id:
        command.extend(["--resume", session_id])
    return command


def codebuddy_env(home: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["CODEBUDDY_CONFIG_DIR"] = str(home)
    env["CODEBUDDY_DISABLE_AUTO_MEMORY"] = "1"
    env["CODEBUDDY_CODE_DISABLE_AUTO_MEMORY"] = "1"
    env["CODEBUDDY_SKIP_BUILTIN_MARKETPLACE"] = "1"
    env["CODEBUDDY_DISABLE_FORK_SUBAGENT"] = "1"
    env["CODEBUDDY_DISABLE_CRON"] = "1"
    env["CODEBUDDY_DISABLE_BACKGROUND_TASKS"] = "1"
    env["DISABLE_TELEMETRY"] = "1"
    env["DISABLE_ERROR_REPORTING"] = "1"
    env["DISABLE_AUTOUPDATER"] = "1"
    return env


def codebuddy_turn(
    *,
    codebuddy_bin: str,
    prompt: str,
    model: str,
    reasoning: str,
    timeout: int,
    cwd: Path,
    home: Path,
    session_id: str | None = None,
) -> dict[str, Any]:
    command = build_codebuddy_command(
        codebuddy_bin=codebuddy_bin,
        prompt=prompt,
        model=model,
        reasoning=reasoning,
        session_id=session_id,
    )
    started = time.monotonic()
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=timeout,
            env=codebuddy_env(home),
        )
        parsed = parse_codebuddy_payload(result.stdout)
        ok = result.returncode == 0 and not parsed.get("is_error")
        if parsed.get("stop_reason") in {"error_during_execution", "error_max_turns", "error_max_budget_usd"}:
            ok = False
        return {
            "ok": ok,
            "returncode": result.returncode,
            "duration_seconds": round(time.monotonic() - started, 3),
            "error": (result.stderr or "")[-1000:] if not ok else "",
            "session_id": parsed.get("session_id") or "",
            "usage": parsed.get("usage") or dict(EMPTY_USAGE),
            "event_types": ["codebuddy.headless"],
            "model_slug": parsed.get("model_slug") or "",
            "cost_usd": parsed.get("cost_usd"),
            "stop_reason": parsed.get("stop_reason") or "",
            "num_turns": parsed.get("num_turns"),
        }
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "returncode": 124,
            "duration_seconds": round(time.monotonic() - started, 3),
            "error": f"timeout after {timeout}s",
            "session_id": "",
            "usage": dict(EMPTY_USAGE),
            "event_types": [],
            "model_slug": "",
            "cost_usd": None,
            "stop_reason": "timeout",
            "num_turns": None,
        }


def host_turn(
    *,
    host: str,
    prompt: str,
    model: str,
    reasoning: str,
    timeout: int,
    cwd: Path,
    grok_bin: str,
    codebuddy_bin: str,
    codebuddy_home: Path | None,
    session_id: str | None = None,
) -> dict[str, Any]:
    if host == "workbuddy":
        if codebuddy_home is None:
            raise ValueError("codebuddy_home is required for the workbuddy host")
        return codebuddy_turn(
            codebuddy_bin=codebuddy_bin,
            prompt=prompt,
            model=model,
            reasoning=reasoning,
            timeout=timeout,
            cwd=cwd,
            home=codebuddy_home,
            session_id=session_id,
        )
    return grok_turn(
        grok_bin=grok_bin,
        prompt=prompt,
        model=model,
        reasoning=reasoning,
        timeout=timeout,
        cwd=cwd,
        session_id=session_id,
    )


def skipped_continuation() -> dict[str, Any]:
    return {
        "ok": False,
        "returncode": 125,
        "duration_seconds": None,
        "error": "continuation skipped because the correction turn did not complete",
        "session_id": "",
        "usage": dict(EMPTY_USAGE),
        "event_types": [],
        "model_slug": "",
        "cost_usd": None,
        "stop_reason": "skipped",
        "num_turns": None,
    }


def write_evidence(path: Path, text: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path.name


def unevaluable_reason(correction_turn: dict[str, Any], continuation_turn: dict[str, Any]) -> str:
    if correction_turn.get("ok") and continuation_turn.get("ok"):
        return ""
    if correction_turn.get("returncode") == 124 or correction_turn.get("stop_reason") == "timeout":
        return "correction_timeout"
    if continuation_turn.get("returncode") == 124 or continuation_turn.get("stop_reason") == "timeout":
        return "continuation_timeout"
    if continuation_turn.get("stop_reason") == "skipped" or continuation_turn.get("returncode") == 125:
        return "continuation_skipped"
    if not correction_turn.get("ok"):
        return "correction_failed"
    return "continuation_failed"


def infrastructure_failure(turn: dict[str, Any]) -> str:
    error = (turn.get("error") or "").lower()
    if turn.get("returncode") == 127:
        return "host executable not found"
    if "no such file" in error and "grok" in error:
        return "grok binary missing"
    if "not found" in error and "grok" in error:
        return "grok binary missing"
    if "no such file" in error and "codebuddy" in error:
        return "codebuddy binary missing"
    if "not found" in error and "codebuddy" in error:
        return "codebuddy binary missing"
    return ""


def run_agent_case(
    *,
    case: dict[str, Any],
    condition: str,
    repeat: int,
    model: str,
    reasoning: str,
    grok_bin: str,
    timeout: int,
    work_root: Path,
    evidence_root: Path,
    host: str = "grok",
    codebuddy_bin: str = "codebuddy",
    codebuddy_home: Path | None = None,
) -> dict[str, Any]:
    run_name = f"{case['id']}__{condition}__r{repeat}"
    workspace = work_root / run_name
    before = prepare_workspace(case, workspace, condition)

    set_eval_turn(workspace, "correction")
    correction_turn = host_turn(
        host=host,
        grok_bin=grok_bin,
        codebuddy_bin=codebuddy_bin,
        codebuddy_home=codebuddy_home,
        prompt=condition_prompt(condition, case),
        model=model,
        reasoning=reasoning,
        timeout=timeout,
        cwd=workspace,
    )
    infra = infrastructure_failure(correction_turn)
    if infra:
        raise RuntimeError(f"{run_name}: collection/infrastructure failure: {infra}")
    correction_score = score_workspace(
        workspace,
        before,
        case,
        continuation=False,
    )
    correction_patch = artifact_patch(workspace)
    correction_patch_rel = f"patches/{run_name}.correction.patch"
    write_evidence(evidence_root / correction_patch_rel, correction_patch)
    save_artifact_tree(workspace, evidence_root / "trees" / run_name / "correction")

    if correction_turn["ok"] and correction_turn.get("session_id"):
        set_eval_turn(workspace, "continuation")
        continuation_turn = host_turn(
            host=host,
            grok_bin=grok_bin,
            codebuddy_bin=codebuddy_bin,
            codebuddy_home=codebuddy_home,
            prompt=case["continuation_prompt"],
            model=model,
            reasoning=reasoning,
            timeout=timeout,
            cwd=workspace,
            session_id=correction_turn["session_id"],
        )
        infra = infrastructure_failure(continuation_turn)
        if infra:
            raise RuntimeError(f"{run_name}: collection/infrastructure failure: {infra}")
    else:
        continuation_turn = skipped_continuation()
    continuation_score = score_workspace(
        workspace,
        before,
        case,
        continuation=True,
    )
    continuation_patch = artifact_patch(workspace)
    continuation_patch_rel = f"patches/{run_name}.continuation.patch"
    write_evidence(evidence_root / continuation_patch_rel, continuation_patch)
    save_artifact_tree(workspace, evidence_root / "trees" / run_name / "continuation")
    journal = read_tool_journal(workspace)
    write_evidence(
        evidence_root / "tool-logs" / f"{run_name}.json",
        json.dumps(journal, ensure_ascii=False, indent=2) + "\n",
    )

    public_correction = public_turn(correction_turn)
    public_continuation = public_turn(continuation_turn)
    evaluable = bool(public_correction["ok"] and public_continuation["ok"])
    return {
        "run": run_name,
        "case_id": case["id"],
        "case_type": case.get("case_type", "cleanup"),
        "condition": condition,
        "repeat": repeat,
        "evaluable": evaluable,
        "unevaluable_reason": unevaluable_reason(public_correction, public_continuation),
        "artifact_delivery": bool(
            evaluable
            and correction_score["artifact_success"]
            and continuation_score["artifact_success"]
        ),
        "correction": correction_score,
        "continuation": continuation_score,
        "correction_turn": public_correction,
        "continuation_turn": public_continuation,
        "total_usage": merge_usage(public_correction["usage"], public_continuation["usage"]),
        "total_cost_usd": merge_optional_numbers(
            public_correction.get("cost_usd"),
            public_continuation.get("cost_usd"),
        ),
        "total_cost_usd_estimated": True,
        "total_duration_seconds": merge_optional_numbers(
            public_correction.get("duration_seconds"),
            public_continuation.get("duration_seconds"),
        ),
        "correction_patch": correction_patch_rel,
        "continuation_patch": continuation_patch_rel,
        "patch": continuation_patch_rel,
        "patch_sha256": sha256_bytes(continuation_patch.encode("utf-8")),
        "tool_journal": {
            "counts": journal["counts"],
            "events": journal["events"],
        },
    }


def wilson_interval(successes: int, total: int) -> tuple[float, float]:
    if total == 0:
        return (0.0, 0.0)
    z = 1.959963984540054
    proportion = successes / total
    denominator = 1 + z * z / total
    centre = (proportion + z * z / (2 * total)) / denominator
    margin = z * math.sqrt(
        (proportion * (1 - proportion) + z * z / (4 * total)) / total
    ) / denominator
    return (max(0.0, centre - margin), min(1.0, centre + margin))


def record_evaluable(record: dict[str, Any]) -> bool:
    if "evaluable" in record:
        return bool(record["evaluable"])
    correction = record.get("correction_turn") or {}
    continuation = record.get("continuation_turn") or {}
    return bool(correction.get("ok") and continuation.get("ok"))


def optional_median(values: list[Any]) -> Any:
    if not values or any(value is None for value in values):
        return None
    return statistics.median(values)


def optional_sum(values: list[Any]) -> Any:
    if not values or any(value is None for value in values):
        return None
    return sum(values)


def summarize_runs(records: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    present_conditions = {record["condition"] for record in records}
    for condition in [item for item in CONDITION_ORDER if item in present_conditions]:
        selected = [record for record in records if record["condition"] == condition]
        attempted = len(selected)
        evaluable = sum(record_evaluable(record) for record in selected)
        unevaluable = attempted - evaluable
        successes = sum(bool(record.get("artifact_delivery")) for record in selected)
        lower, upper = wilson_interval(successes, attempted)
        evaluable_rate = round(100 * successes / evaluable, 1) if evaluable else None
        metric_source = [record for record in selected if record_evaluable(record)]
        metric_rates: dict[str, float | None] = {}
        for metric in (
            "active_requirements_preserved",
            "artifact_residue_free",
            "process_trace_artifact_free",
            "retired_surface_removed",
            "no_unrelated_mutation",
            "scope_clean",
            "hidden_check_passed",
            "transient_state_clean",
        ):
            if not metric_source:
                metric_rates[metric] = None
                continue
            metric_rates[metric] = round(
                100
                * sum(
                    record["correction"]["metrics"][metric]
                    and record["continuation"]["metrics"][metric]
                    for record in metric_source
                )
                / len(metric_source),
                1,
            )
        checker_events = []
        leftover_state = 0
        for record in selected:
            journal = record.get("tool_journal") or {}
            counts = journal.get("counts", journal) if isinstance(journal, dict) else {}
            checker_events.append(counts if isinstance(counts, dict) else {})
            leftover_state += int(
                not record.get("correction", {}).get("metrics", {}).get("transient_state_clean", True)
                or not record.get("continuation", {}).get("metrics", {}).get(
                    "transient_state_clean", True
                )
            )
        summary[condition] = {
            "attempted": attempted,
            "evaluable": evaluable,
            "unevaluable": unevaluable,
            "runs": attempted,
            "valid_runs": evaluable,
            "invalid_runs": unevaluable,
            "artifact_deliveries": successes,
            "artifact_delivery_rate": round(100 * successes / attempted, 1) if attempted else None,
            "artifact_delivery_rate_evaluable": evaluable_rate,
            "artifact_delivery_wilson_95": [round(100 * lower, 1), round(100 * upper, 1)],
            "metric_rates": metric_rates,
            "median_total_tokens": optional_median(
                [
                    None
                    if (record.get("total_usage") or {}).get("input_tokens") is None
                    or (record.get("total_usage") or {}).get("output_tokens") is None
                    else int((record.get("total_usage") or {}).get("input_tokens"))
                    + int((record.get("total_usage") or {}).get("output_tokens"))
                    for record in selected
                ]
            ),
            "median_output_tokens": optional_median(
                [(record.get("total_usage") or {}).get("output_tokens") for record in selected]
            ),
            "median_duration_seconds": optional_median(
                [record.get("total_duration_seconds") for record in selected]
            ),
            "total_usage": {
                key: optional_sum(
                    [(record.get("total_usage") or {}).get(key) for record in selected]
                )
                for key in USAGE_KEYS
            },
            "total_duration_seconds": optional_sum(
                [record.get("total_duration_seconds") for record in selected]
            ),
            "total_estimated_usd": optional_sum(
                [record.get("total_cost_usd") for record in selected]
            ),
            "diagnostics": {
                "checker_init": sum(int((item or {}).get("checker_init") or 0) for item in checker_events),
                "checker_check": sum(int((item or {}).get("checker_check") or 0) for item in checker_events),
                "checker_cleanup_flag": sum(
                    int((item or {}).get("checker_cleanup_flag") or 0) for item in checker_events
                ),
                "leftover_state_runs": leftover_state,
            },
        }
    return summary


FORBIDDEN_RECORD_KEYS = {
    "session_id",
    "response",
    "thought",
    "response_sha256",
    "response_chars",
}


def freeze_source_files() -> list[Path]:
    roots = [
        REPO_ROOT / "SKILL.md",
        REPO_ROOT / "scripts" / "stop_chatter.py",
        REPO_ROOT / "scripts" / "install.py",
        REPO_ROOT / "evals" / "benchmark.py",
        REPO_ROOT / "evals" / "publish_artifact_view.py",
        REPO_ROOT / "evals" / "evaluation-plan.md",
        REPO_ROOT / "evals" / "README.md",
    ]
    cases = [
        path
        for path in sorted((REPO_ROOT / "evals" / "cases").rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts
    ]
    return roots + cases


def write_freeze(output: Path) -> dict[str, Any]:
    freeze_root = output / "freeze"
    freeze_root.mkdir(parents=True, exist_ok=True)
    files: dict[str, str] = {}
    for path in freeze_source_files():
        relative = path.relative_to(REPO_ROOT).as_posix()
        destination = freeze_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
        files[relative] = sha256_bytes(destination.read_bytes())
    meta = {
        "created_at": utc_now(),
        "benchmark_version": BENCHMARK_VERSION,
        "files": files,
    }
    (freeze_root / "freeze.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return meta


def verify_freeze(freeze_root: Path) -> dict[str, Any]:
    meta_path = freeze_root / "freeze.json"
    if not meta_path.is_file():
        raise RuntimeError("refuse to use live sources: freeze/freeze.json is missing")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    files = meta.get("files") or {}
    if not files:
        raise RuntimeError("freeze snapshot lists no files")
    for relative, expected in files.items():
        path = freeze_root / relative
        if not path.is_file():
            raise RuntimeError(f"freeze drift: missing {relative}")
        actual = sha256_bytes(path.read_bytes())
        if actual != expected:
            raise RuntimeError(f"freeze drift: {relative}")
    return meta


def load_frozen_benchmark(result_root: Path) -> Any:
    freeze_root = result_root / "freeze"
    verify_freeze(freeze_root)
    spec = importlib.util.spec_from_file_location(
        "frozen_chatterbench",
        freeze_root / "evals" / "benchmark.py",
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot import frozen evals/benchmark.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def planned_campaign_runs(
    cases: list[dict[str, Any]],
    conditions: list[str],
    repeats: int,
) -> list[dict[str, Any]]:
    planned: list[dict[str, Any]] = []
    for repeat in range(1, repeats + 1):
        for case_index, case in enumerate(cases):
            for condition in schedule_conditions(conditions, repeat, case_index):
                planned.append(
                    {
                        "case": case,
                        "condition": condition,
                        "repeat": repeat,
                        "run": f"{case['id']}__{condition}__r{repeat}",
                    }
                )
    return planned


def scan_forbidden_record_keys(value: Any) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key in FORBIDDEN_RECORD_KEYS:
                found.append(key)
            found.extend(scan_forbidden_record_keys(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(scan_forbidden_record_keys(child))
    return found


def validate_run_integrity(output: Path, run_name: str) -> list[str]:
    problems: list[str] = []
    record_path = output / "runs" / f"{run_name}.json"
    if not record_path.is_file():
        return [f"missing run json: {run_name}"]
    record = json.loads(record_path.read_text(encoding="utf-8"))
    for relative, kind in (
        (f"trees/{run_name}/correction", "dir"),
        (f"trees/{run_name}/continuation", "dir"),
        (f"patches/{run_name}.correction.patch", "file"),
        (f"patches/{run_name}.continuation.patch", "file"),
    ):
        path = output / relative
        if kind == "dir" and not path.is_dir():
            problems.append(f"missing {relative}")
        if kind == "file" and not path.is_file():
            problems.append(f"missing {relative}")
    leaked = scan_forbidden_record_keys(record)
    if leaked:
        problems.append("forbidden keys: " + ", ".join(sorted(set(leaked))))
    if "evaluable" not in record:
        problems.append("missing evaluable")
    if "artifact_delivery" not in record:
        problems.append("missing artifact_delivery")
    for turn_key in ("correction_turn", "continuation_turn"):
        turn = record.get(turn_key)
        if not isinstance(turn, dict):
            problems.append(f"missing {turn_key}")
            continue
        usage = turn.get("usage")
        if not isinstance(usage, dict) or any(key not in usage for key in USAGE_KEYS):
            problems.append(f"{turn_key} usage keys missing")
        for field in ("duration_seconds", "num_turns", "stop_reason", "model_slug", "cost_usd"):
            if field not in turn:
                problems.append(f"{turn_key} missing {field}")
    usage = record.get("total_usage")
    if not isinstance(usage, dict) or any(key not in usage for key in USAGE_KEYS):
        problems.append("total_usage keys missing")
    return problems


def run_record_status(output: Path, run_name: str) -> str:
    record_path = output / "runs" / f"{run_name}.json"
    if not record_path.is_file():
        return "absent"
    if validate_run_integrity(output, run_name):
        return "incomplete"
    return "complete"


def load_run_record(output: Path, run_name: str) -> dict[str, Any] | None:
    path = output / "runs" / f"{run_name}.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def stub_incomplete_record(item: dict[str, Any], problems: list[str]) -> dict[str, Any]:
    empty_turn = public_turn(
        {
            "ok": False,
            "returncode": 126,
            "duration_seconds": None,
            "usage": dict(EMPTY_USAGE),
            "event_types": [],
            "error": "; ".join(problems),
            "model_slug": "",
            "cost_usd": None,
            "num_turns": None,
            "stop_reason": "incomplete_record",
        }
    )
    return {
        "run": item["run"],
        "case_id": item["case"]["id"],
        "case_type": item["case"].get("case_type", "cleanup"),
        "condition": item["condition"],
        "repeat": item["repeat"],
        "evaluable": False,
        "unevaluable_reason": "incomplete_record",
        "artifact_delivery": False,
        "correction": {"artifact_success": False, "metrics": {}},
        "continuation": {"artifact_success": False, "metrics": {}},
        "correction_turn": empty_turn,
        "continuation_turn": empty_turn,
        "total_usage": dict(EMPTY_USAGE),
        "total_cost_usd": None,
        "total_cost_usd_estimated": True,
        "total_duration_seconds": None,
        "correction_patch": "",
        "continuation_patch": "",
        "patch": "",
        "patch_sha256": "",
        "tool_journal": {"counts": {}, "events": []},
    }


def summarize_cases(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    present_conditions = {record["condition"] for record in records}
    conditions = [item for item in CONDITION_ORDER if item in present_conditions]
    result: list[dict[str, Any]] = []
    for case_id in sorted({record["case_id"] for record in records}):
        case_records = [record for record in records if record["case_id"] == case_id]
        entry: dict[str, Any] = {
            "case_id": case_id,
            "case_type": case_records[0].get("case_type", "cleanup"),
            "conditions": {},
        }
        for condition in conditions:
            selected = [record for record in case_records if record["condition"] == condition]
            successes = sum(bool(record.get("artifact_delivery")) for record in selected)
            attempted = len(selected)
            unevaluable = sum(not record_evaluable(record) for record in selected)
            entry["conditions"][condition] = {
                "runs": attempted,
                "attempted": attempted,
                "evaluable": attempted - unevaluable,
                "unevaluable": unevaluable,
                "artifact_deliveries": successes,
                "artifact_delivery_rate": round(100 * successes / attempted, 1) if attempted else None,
            }
        result.append(entry)
    return result


def summarize_case_types(records: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for case_type in sorted({record.get("case_type", "cleanup") for record in records}):
        type_records = [
            record for record in records if record.get("case_type", "cleanup") == case_type
        ]
        result[case_type] = summarize_runs(type_records)
    return result


def make_corpus_state(sample: dict[str, Any]) -> dict[str, Any]:
    path = sample.get("path", "artifact.txt")
    requirement_paths = sample.get("requirement_paths", [path])
    return {
        "schema_version": 1,
        "ready": True,
        "active_target": {
            "goal": "Keep the current artifact.",
            "requirements": [{"id": "R1", "text": "Keep it.", "paths": requirement_paths}],
            "meta_constraints": [
                {
                    "id": "M1",
                    "text": "Keep execution concise.",
                    "leak_markers": sample.get("meta_markers", []),
                }
            ],
        },
        "retired": [
            {
                "id": "X1",
                "label": sample.get("retired_label", "retired-token"),
                "aliases": sample.get("retired_aliases", []),
                "scope": "task",
            }
        ],
        "delivery": {
            "ignore_paths": sample.get("ignore_paths", []),
            "allow_process_trace_paths": sample.get("allow_process_trace_paths", []),
            "exceptions": sample.get("exceptions", []),
        },
    }


def evaluate_gate_corpus() -> dict[str, Any]:
    samples = json.loads(GATE_CORPUS.read_text(encoding="utf-8"))["samples"]
    results: list[dict[str, Any]] = []
    for sample in samples:
        with tempfile.TemporaryDirectory(prefix="stop-chatter-gate-corpus-") as temporary:
            root = Path(temporary)
            state_path = root / ".stop-chatter" / "state.json"
            state_path.parent.mkdir(parents=True)
            state_path.write_text(
                json.dumps(make_corpus_state(sample), ensure_ascii=False), encoding="utf-8"
            )
            artifact = root / sample.get("path", "artifact.txt")
            artifact.parent.mkdir(parents=True, exist_ok=True)
            if "content_hex" in sample:
                artifact.write_bytes(bytes.fromhex(sample["content_hex"]))
            else:
                artifact.write_text(sample.get("content", ""), encoding="utf-8")
            result = run_command(
                [
                    sys.executable,
                    str(GATE),
                    "check",
                    "--root",
                    str(root),
                    "--format",
                    "json",
                    sample.get("path", "artifact.txt"),
                ],
                timeout=30,
            )
            payload = json.loads(result.stdout)
            observed = sorted({item["code"] for item in payload.get("violations", [])})
            expected = sorted(sample.get("expected_codes", []))
            results.append(
                {
                    "id": sample["id"],
                    "expected_codes": expected,
                    "observed_codes": observed,
                    "exact_match": expected == observed,
                }
            )

    true_positive = false_positive = false_negative = 0
    binary_tp = binary_fp = binary_tn = binary_fn = 0
    for result in results:
        expected = set(result["expected_codes"])
        observed = set(result["observed_codes"])
        true_positive += len(expected & observed)
        false_positive += len(observed - expected)
        false_negative += len(expected - observed)
        expected_block = bool(expected)
        observed_block = bool(observed)
        if expected_block and observed_block:
            binary_tp += 1
        elif expected_block:
            binary_fn += 1
        elif observed_block:
            binary_fp += 1
        else:
            binary_tn += 1

    precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else 1.0
    recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    binary_precision = binary_tp / (binary_tp + binary_fp) if binary_tp + binary_fp else 1.0
    binary_recall = binary_tp / (binary_tp + binary_fn) if binary_tp + binary_fn else 1.0
    binary_f1 = (
        2 * binary_precision * binary_recall / (binary_precision + binary_recall)
        if binary_precision + binary_recall
        else 0.0
    )
    return {
        "evaluated_at": utc_now(),
        "corpus_samples": len(results),
        "code_level": {
            "true_positive": true_positive,
            "false_positive": false_positive,
            "false_negative": false_negative,
            "precision": round(100 * precision, 1),
            "recall": round(100 * recall, 1),
            "f1": round(100 * f1, 1),
        },
        "binary_block_decision": {
            "true_positive": binary_tp,
            "false_positive": binary_fp,
            "true_negative": binary_tn,
            "false_negative": binary_fn,
            "precision": round(100 * binary_precision, 1),
            "recall": round(100 * binary_recall, 1),
            "f1": round(100 * binary_f1, 1),
        },
        "exact_match_rate": round(100 * sum(item["exact_match"] for item in results) / len(results), 1),
        "samples": results,
    }


def git_value(*arguments: str) -> str:
    result = run_command(["git", *arguments], cwd=REPO_ROOT, timeout=30)
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def codex_version(codex_bin: str) -> str:
    result = run_command([codex_bin, "--version"], timeout=30)
    return result.stdout.strip() if result.returncode == 0 else "unavailable"


def _fmt_number(value: Any, digits: int | None = None) -> str:
    if value is None:
        return "unknown"
    if isinstance(value, float) and digits is not None:
        return f"{value:.{digits}f}"
    return str(value)


def _fmt_metric(value: Any) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):.1f}%"


def summary_markdown(
    manifest: dict[str, Any],
    agent: dict[str, Any],
    gate: dict[str, Any],
    cases: list[dict[str, Any]],
    case_types: dict[str, Any],
    overhead: dict[str, Any] | None = None,
) -> str:
    del overhead
    freeze_files = ((manifest.get("freeze") or {}).get("files") or {})
    lines = [
        "# ChatterBench result (SCE-1.2)",
        "",
        f"- Date: `{manifest['started_at']}`",
        f"- Host: `{manifest['host']}` / `{manifest['host_version']}`",
        f"- Model: `{manifest['model']}` at `{manifest['reasoning']}` reasoning",
        f"- Cases: `{manifest['case_count']}`; repeats: `{manifest['repeats']}`",
        f"- Repository commit (not a source freeze): `{manifest['repository_commit']}`",
        f"- Repository dirty at start: `{str(manifest['repository_dirty']).lower()}`",
        f"- Frozen source files: `{len(freeze_files)}`",
        f"- Instruction envelope: {manifest['instruction_envelope']}",
        "",
        "## Deliverable behavior",
        "",
        "| Condition | Attempts | Successes | Unevaluable | Success of attempts | Current requirements | Residue absent | Process labels absent | Retired surface removed |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    h4b_failures = 0
    for condition, values in agent.items():
        metrics = values["metric_rates"]
        interval = values["artifact_delivery_wilson_95"]
        residue = metrics.get("artifact_residue_free")
        surface = metrics.get("retired_surface_removed", metrics.get("scope_clean"))
        unrelated = metrics.get("no_unrelated_mutation")
        if unrelated is not None:
            h4b_failures += max(0, 100.0 - float(unrelated))
        attempted = values.get("attempted", values.get("runs", 0))
        rate = values.get("artifact_delivery_rate")
        rate_text = "unknown" if rate is None else f"{rate:.1f}%"
        lines.append(
            f"| {condition} | {attempted} | {values['artifact_deliveries']} "
            f"| {values.get('unevaluable', values.get('invalid_runs', 0))} "
            f"| {rate_text}; 95% CI {interval[0]:.1f}–{interval[1]:.1f} "
            f"| {_fmt_metric(metrics.get('active_requirements_preserved'))} "
            f"| {_fmt_metric(residue)} "
            f"| {_fmt_metric(metrics.get('process_trace_artifact_free'))} "
            f"| {_fmt_metric(surface)} |"
        )
    lines.extend(["", "## H4b unrelated or protected-file mutation", ""])
    if h4b_failures <= 0:
        lines.append(
            "Observed failures: 0. Do not treat this as evidence that edits stayed in bounds."
        )
    else:
        lines.append("| Condition | No unrelated/protected mutation |")
        lines.append("|---|---:|")
        for condition, values in agent.items():
            rate = values["metric_rates"].get("no_unrelated_mutation")
            if rate is None:
                continue
            lines.append(f"| {condition} | {rate:.1f}% |")
    lines.extend(
        [
            "",
            "## Attempts, evaluable runs, and absolute cost",
            "",
            "CLI USD is an estimate from the host JSON, not a billing invoice. "
            "Missing token, time, or USD values stay unknown; they are not filled with 0. "
            "Cache tokens are stored separately and are not added into input tokens.",
            "",
            "| Condition | Attempts | Evaluable | Unevaluable | Input tokens | Cached input | Output tokens | Agent seconds | Estimated USD | Median seconds |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for condition, values in agent.items():
        usage = values.get("total_usage") or {}
        duration = values.get("total_duration_seconds")
        lines.append(
            f"| {condition} | {values.get('attempted', values.get('runs', 0))} "
            f"| {values.get('evaluable', values.get('valid_runs', 0))} "
            f"| {values.get('unevaluable', values.get('invalid_runs', 0))} "
            f"| {_fmt_number(usage.get('input_tokens'))} "
            f"| {_fmt_number(usage.get('cached_input_tokens'))} "
            f"| {_fmt_number(usage.get('output_tokens'))} "
            f"| {_fmt_number(duration, 1)} "
            f"| {_fmt_number(values.get('total_estimated_usd'), 4)} "
            f"| {_fmt_number(values.get('median_duration_seconds'), 1)} |"
        )
    lines.extend(
        [
            "",
            "## Protocol diagnostics (not deliverable quality)",
            "",
            "| Condition | checker init | checker check | cleanup flag | leftover state runs |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for condition, values in agent.items():
        diagnostics = values.get("diagnostics") or {}
        lines.append(
            f"| {condition} | {diagnostics.get('checker_init', 0)} "
            f"| {diagnostics.get('checker_check', 0)} "
            f"| {diagnostics.get('checker_cleanup_flag', 0)} "
            f"| {diagnostics.get('leftover_state_runs', 0)} |"
        )
    lines.extend(
        [
            "",
            "## Per-case deliverable success",
            "",
            "| Case | Type | Baseline | Light | Guarded |",
            "|---|---|---:|---:|---:|",
        ]
    )
    for case in cases:
        values = case["conditions"]
        baseline = values.get("baseline", {"artifact_deliveries": 0, "runs": 0})
        light = values.get("light", {"artifact_deliveries": 0, "runs": 0})
        guarded = values.get("guarded", {"artifact_deliveries": 0, "runs": 0})
        lines.append(
            f"| {case['case_id']} | {case['case_type']} "
            f"| {baseline['artifact_deliveries']}/{baseline.get('attempted', baseline.get('runs', 0))} "
            f"| {light['artifact_deliveries']}/{light.get('attempted', light.get('runs', 0))} "
            f"| {guarded['artifact_deliveries']}/{guarded.get('attempted', guarded.get('runs', 0))} |"
        )
    lines.extend(["", "## Case-type controls", ""])
    for case_type, type_summary in case_types.items():
        rates = ", ".join(
            f"{condition} {values['artifact_deliveries']}/{values.get('attempted', values.get('runs', 0))}"
            for condition, values in type_summary.items()
        )
        lines.append(f"- `{case_type}`: {rates}")
    lines.extend(
        [
            "",
            "Deliverable success is all-or-nothing across both completed turns. "
            "It requires current requirements and hidden checks to pass, retired terms and process "
            "labels to be absent from remaining files, retired-surface files to be gone, and no "
            "unrelated or protected-file mutation. Transient checker state and checker call counts "
            "are diagnostics only. Assistant reply wording is not scored or stored. Timeouts, "
            "host failures, and incomplete protocol stays in the attempt count as unevaluable, "
            "not silent exclusions. Do not read the residue and retired-surface columns as one fact.",
            "",
            "## Deterministic gate corpus",
            "",
            f"- Samples: `{gate['corpus_samples']}`",
            f"- Code-level precision / recall / F1: `{gate['code_level']['precision']:.1f}%` / "
            f"`{gate['code_level']['recall']:.1f}%` / `{gate['code_level']['f1']:.1f}%`",
            f"- Binary block precision / recall / F1: `{gate['binary_block_decision']['precision']:.1f}%` / "
            f"`{gate['binary_block_decision']['recall']:.1f}%` / "
            f"`{gate['binary_block_decision']['f1']:.1f}%`",
            f"- Exact expected-code match: `{gate['exact_match_rate']:.1f}%`",
            "",
            "The corpus includes unlisted semantic aliases and substring collisions. These are "
            "known limits, not excluded failures.",
            "",
        ]
    )
    return "\n".join(lines)


def command_gate(args: argparse.Namespace) -> int:
    result = evaluate_gate_corpus()
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0


def command_agent(args: argparse.Namespace) -> int:
    cases = load_cases(args.cases)
    conditions = list(dict.fromkeys(args.conditions))
    invalid = sorted(set(conditions) - {"baseline", "light", "guarded"})
    if invalid:
        raise ValueError(f"unknown condition(s): {', '.join(invalid)}")
    started_at = utc_now()
    slug = (
        started_at[:10]
        + "-"
        + started_at[11:19].replace(":", "")
        + "-"
        + args.model.replace("/", "-")
    )
    output = Path(args.output).resolve() if args.output else REPO_ROOT / "evals" / "results" / slug
    output.mkdir(parents=True, exist_ok=True)
    existing = [path for path in output.iterdir() if path.name != ".DS_Store"]
    freeze_root = output / "freeze"
    if existing and not (freeze_root / "freeze.json").is_file():
        raise ValueError(
            f"output directory is not empty and has no freeze snapshot: {output}"
        )
    if (freeze_root / "freeze.json").is_file():
        freeze_meta = verify_freeze(freeze_root)
        resuming = True
    else:
        freeze_meta = write_freeze(output)
        resuming = False

    host = getattr(args, "host", "grok")
    grok_bin = args.grok_bin
    codebuddy_bin = getattr(args, "codebuddy_bin", str(DEFAULT_CODEBUDDY_BIN))
    if host == "workbuddy":
        envelope = (
            "WorkBuddy CodeBuddy CLI headless JSON; isolated CODEBUDDY_CONFIG_DIR "
            "with the user glm-5 Coding Plan custom model; auto-memory off; builtin "
            "marketplace skipped; no MCP; no subagents; Skill/file tools only. "
            "One new session per task; only the continuation turn resumes it. "
            "Project .agents/skills/stop-chatter is installed for light/guarded via "
            "--host cursor, then copied to .codebuddy/skills/stop-chatter. Envelope "
            "names Light or Guarded only; no $stop-chatter and no checker command in "
            "the eval prompt. Guarded state is not pre-seeded; the model initializes "
            "from the visible task and Skill, and that cost is measured. CLI USD is "
            "omitted when the host reports 0 for a subscription plan."
        )
        host_label = "WorkBuddy CodeBuddy CLI"
        host_version = codebuddy_version(codebuddy_bin)
        host_binary = codebuddy_bin
    else:
        envelope = (
            "Grok Build headless JSON; Cursor/Claude user skills disabled via env; "
            "--no-memory --disable-web-search --no-subagents --verbatim --always-approve. "
            "One new session per task; only the continuation turn resumes it. "
            "Project .agents/skills/stop-chatter is installed only for light/guarded "
            "via --host cursor. Envelope names Light or Guarded only; no $stop-chatter "
            "and no checker command in the eval prompt. Guarded state is not pre-seeded; "
            "the model initializes from the visible task and Skill, and that cost is measured."
        )
        host_label = "Grok Build CLI"
        host_version = grok_version(grok_bin)
        host_binary = grok_bin
    manifest = {
        "schema_version": 5,
        "benchmark_version": BENCHMARK_VERSION,
        "started_at": started_at,
        "host": host_label,
        "host_version": host_version,
        "host_binary": host_binary,
        "model": args.model,
        "reasoning": args.reasoning,
        "conditions": conditions,
        "case_ids": [case["id"] for case in cases],
        "case_count": len(cases),
        "repeats": args.repeats,
        "planned_runs": len(cases) * len(conditions) * args.repeats,
        "repository_commit": git_value("rev-parse", "HEAD"),
        "repository_dirty": bool(git_value("status", "--porcelain")),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "instruction_envelope": envelope,
        "continuation_turn": True,
        "independent_gold_visible_to_agent": False,
        "guarded_task_state_visible_to_agent": False,
        "quality_scope": "deliverables_only",
        "assistant_reply_scored": False,
        "assistant_reply_stored": False,
        "per_turn_patches": True,
        "rescore_from_trees": True,
        "cost_usd_estimated": True,
        "official_cost": "absolute_duration_tokens_estimated_usd",
        "condition_schedule": "rotate_by_repeat_and_case",
        "resume": resuming,
        "freeze": freeze_meta,
    }
    prior_manifest_path = output / "manifest.json"
    if resuming and prior_manifest_path.is_file():
        prior = json.loads(prior_manifest_path.read_text(encoding="utf-8"))
        manifest["started_at"] = prior.get("started_at", started_at)
        manifest["resume"] = True
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    planned = planned_campaign_runs(cases, conditions, args.repeats)
    first_group = planned[: len(conditions)]
    work_root = Path(tempfile.mkdtemp(prefix="stop-chatter-agent-eval-"))
    codebuddy_home = None
    if host == "workbuddy":
        codebuddy_home = write_codebuddy_home(work_root / "codebuddy-home")
    records: list[dict[str, Any]] = []
    total = len(planned)
    try:
        for current, item in enumerate(planned, start=1):
            run_name = item["run"]
            status = run_record_status(output, run_name)
            if status == "complete":
                record = load_run_record(output, run_name)
                assert record is not None
                records.append(record)
                print(f"SKIP complete {run_name} ({current}/{total})", flush=True)
            elif status == "incomplete":
                problems = validate_run_integrity(output, run_name)
                record = load_run_record(output, run_name) or stub_incomplete_record(item, problems)
                record["evaluable"] = False
                record["unevaluable_reason"] = record.get("unevaluable_reason") or "incomplete_record"
                record["artifact_delivery"] = False
                records.append(record)
                print(
                    f"SKIP incomplete {run_name} (no retry): {'; '.join(problems)}",
                    flush=True,
                )
            else:
                print(
                    f"RUN {current}/{total} case={item['case']['id']} "
                    f"condition={item['condition']} repeat={item['repeat']}",
                    flush=True,
                )
                record = run_agent_case(
                    case=item["case"],
                    condition=item["condition"],
                    repeat=item["repeat"],
                    model=args.model,
                    reasoning=args.reasoning,
                    grok_bin=grok_bin,
                    timeout=args.timeout,
                    work_root=work_root,
                    evidence_root=output,
                    host=host,
                    codebuddy_bin=codebuddy_bin,
                    codebuddy_home=codebuddy_home,
                )
                run_path = output / "runs" / f"{record['run']}.json"
                run_path.parent.mkdir(parents=True, exist_ok=True)
                run_path.write_text(
                    json.dumps(record, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                problems = validate_run_integrity(output, run_name)
                if problems:
                    raise RuntimeError(
                        f"collection/protocol failure for {run_name}: {'; '.join(problems)}"
                    )
                records.append(record)
                print(
                    f"DONE {record['run']} artifact_delivery={record['artifact_delivery']} "
                    f"evaluable={record['evaluable']}",
                    flush=True,
                )
            if current == len(first_group):
                group_problems: list[str] = []
                for group_item in first_group:
                    name = group_item["run"]
                    if run_record_status(output, name) != "complete":
                        group_problems.extend(
                            validate_run_integrity(output, name) or [f"{name} not complete"]
                        )
                if group_problems:
                    raise RuntimeError(
                        "first condition group failed record integrity; pausing: "
                        + "; ".join(group_problems)
                    )
                print("INTEGRITY first condition group ok", flush=True)
    finally:
        if args.keep_workspaces:
            (output / "workspace-location.txt").write_text(str(work_root) + "\n", encoding="utf-8")
        else:
            shutil.rmtree(work_root, ignore_errors=True)

    gate = evaluate_gate_corpus()
    agent = summarize_runs(records)
    cases_summary = summarize_cases(records)
    case_types = summarize_case_types(records)
    summary = {
        "manifest": manifest,
        "artifact_delivery": {
            "all_cases": agent,
            "cases": cases_summary,
            "case_types": case_types,
        },
        "gate": gate,
    }
    (output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output / "summary.md").write_text(
        summary_markdown(manifest, agent, gate, cases_summary, case_types),
        encoding="utf-8",
    )
    print(f"RESULT {output / 'summary.md'}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run ChatterBench.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    gate = subparsers.add_parser("gate", help="evaluate the deterministic gate corpus")
    gate.add_argument("--output", help="optional JSON output path")
    gate.set_defaults(handler=command_gate)

    agent = subparsers.add_parser("agent", help="run paired agent evaluations")
    agent.add_argument(
        "--host",
        choices=("grok", "workbuddy"),
        default="grok",
        help="grok = Grok Build CLI; workbuddy = WorkBuddy CodeBuddy CLI",
    )
    agent.add_argument(
        "--conditions", nargs="+", default=["baseline", "light", "guarded"]
    )
    agent.add_argument("--cases", nargs="*", help="case ids; defaults to all")
    agent.add_argument("--repeats", type=int, default=3)
    agent.add_argument("--model", default="grok-4.6")
    agent.add_argument(
        "--grok-bin",
        default=str(DEFAULT_GROK_BIN if DEFAULT_GROK_BIN.is_file() else "grok"),
        help="Grok Build CLI executable",
    )
    agent.add_argument(
        "--codebuddy-bin",
        default=str(DEFAULT_CODEBUDDY_BIN if DEFAULT_CODEBUDDY_BIN.is_file() else "codebuddy"),
        help="WorkBuddy CodeBuddy CLI executable",
    )
    agent.add_argument(
        "--codex-bin",
        default=shutil.which("codex") or "codex",
        help="Unused Codex path retained for older tests",
    )
    agent.add_argument(
        "--reasoning",
        choices=("low", "medium", "high", "xhigh", "max"),
        default="medium",
    )
    agent.add_argument("--timeout", type=int, default=600, help="seconds per turn")
    agent.add_argument("--output", help="result directory")
    agent.add_argument("--keep-workspaces", action="store_true")
    agent.set_defaults(handler=command_agent)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if getattr(args, "repeats", 1) < 1:
        raise ValueError("--repeats must be at least 1")
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
