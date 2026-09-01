#!/usr/bin/env python3
"""Reproducible end-to-end benchmark for correction-residue behavior."""

from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import hashlib
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
IGNORED_PREFIXES = (
    ".git/",
    ".agents/",
    ".claude/",
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

    metrics = {
        "active_requirements_preserved": not required_failures,
        "artifact_residue_free": not retired_artifact,
        "process_trace_artifact_free": not trace_artifact,
        "scope_clean": not unexpected_changes and not forbidden_paths_present and not protected_failures,
        "hidden_check_passed": hidden_ok,
        "transient_state_clean": transient_state_clean,
    }
    artifact_success = all(metrics.values())
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


def init_git(root: Path) -> None:
    commands = (
        ["git", "init", "-q"],
        ["git", "config", "user.email", "chatterbench@example.invalid"],
        ["git", "config", "user.name", "ChatterBench"],
        ["git", "add", "-A"],
        ["git", "commit", "-qm", "frozen fixture"],
    )
    for command in commands:
        result = run_command(command, cwd=root, timeout=30)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or f"command failed: {' '.join(command)}")


def prepare_workspace(case: dict[str, Any], destination: Path, condition: str) -> dict[str, bytes]:
    fixture = Path(case["_directory"]) / "fixture"
    shutil.copytree(fixture, destination)
    init_git(destination)
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
                "codex",
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
            handle.write("\n.agents/\n.stop-chatter/\n")
    if condition == "guarded":
        state_dir = destination / ".stop-chatter"
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / ".gitignore").write_text("state.json\n", encoding="utf-8")
        (state_dir / "state.json").write_text(
            json.dumps(make_guard_state(case), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return before


def make_guard_state(case: dict[str, Any]) -> dict[str, Any]:
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
        return "$stop-chatter\nUse Light mode for this task.\n\n" + prompt
    if condition == "guarded":
        return (
            "$stop-chatter\nUse Guarded mode for this task. The frozen task-local state already exists "
            "at .stop-chatter/state.json. Run its deterministic check before delivery, fix only "
            "reported residue or scope failures, run it once more if needed, then remove the "
            "transient state.json.\n\n" + prompt
        )
    raise ValueError(f"unknown condition: {condition}")


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


def public_turn(turn: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": turn["ok"],
        "returncode": turn["returncode"],
        "duration_seconds": turn["duration_seconds"],
        "usage": turn["usage"],
        "event_types": turn.get("event_types", []),
        "error": turn.get("error", ""),
    }


def run_agent_case(
    *,
    case: dict[str, Any],
    condition: str,
    repeat: int,
    model: str,
    reasoning: str,
    codex_bin: str,
    timeout: int,
    work_root: Path,
    evidence_root: Path,
) -> dict[str, Any]:
    run_name = f"{case['id']}__{condition}__r{repeat}"
    workspace = work_root / run_name
    before = prepare_workspace(case, workspace, condition)

    correction_turn = codex_turn(
        codex_bin=codex_bin,
        prompt=condition_prompt(condition, case),
        model=model,
        reasoning=reasoning,
        timeout=timeout,
        cwd=workspace,
    )
    correction_score = score_workspace(
        workspace,
        before,
        case,
        continuation=False,
    )

    if correction_turn["ok"] and correction_turn.get("session_id"):
        continuation_turn = codex_turn(
            codex_bin=codex_bin,
            prompt=case["continuation_prompt"],
            model=model,
            reasoning=reasoning,
            timeout=timeout,
            cwd=workspace,
            session_id=correction_turn["session_id"],
        )
    else:
        continuation_turn = {
            "ok": False,
            "returncode": 125,
            "duration_seconds": 0.0,
            "error": "continuation skipped because the correction turn did not complete",
            "session_id": "",
            "usage": {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0},
            "event_types": [],
        }
    continuation_score = score_workspace(
        workspace,
        before,
        case,
        continuation=True,
    )
    patch = artifact_patch(workspace)
    patch_path = evidence_root / "patches" / f"{run_name}.patch"
    patch_path.parent.mkdir(parents=True, exist_ok=True)
    patch_path.write_text(patch, encoding="utf-8")

    total_usage = {
        key: correction_turn["usage"].get(key, 0) + continuation_turn["usage"].get(key, 0)
        for key in ("input_tokens", "cached_input_tokens", "output_tokens")
    }
    return {
        "run": run_name,
        "case_id": case["id"],
        "case_type": case.get("case_type", "cleanup"),
        "condition": condition,
        "repeat": repeat,
        "artifact_delivery": bool(
            correction_turn["ok"]
            and continuation_turn["ok"]
            and correction_score["artifact_success"]
            and continuation_score["artifact_success"]
        ),
        "correction": correction_score,
        "continuation": continuation_score,
        "correction_turn": public_turn(correction_turn),
        "continuation_turn": public_turn(continuation_turn),
        "total_usage": total_usage,
        "total_duration_seconds": round(
            correction_turn["duration_seconds"] + continuation_turn["duration_seconds"], 3
        ),
        "patch": str(patch_path.relative_to(evidence_root)),
        "patch_sha256": sha256_bytes(patch.encode("utf-8")),
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


def summarize_runs(records: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    present_conditions = {record["condition"] for record in records}
    for condition in [item for item in CONDITION_ORDER if item in present_conditions]:
        selected = [record for record in records if record["condition"] == condition]
        successes = sum(record["artifact_delivery"] for record in selected)
        valid_runs = sum(
            record["correction_turn"]["ok"] and record["continuation_turn"]["ok"]
            for record in selected
        )
        lower, upper = wilson_interval(successes, len(selected))
        metric_rates: dict[str, float] = {}
        for metric in (
            "active_requirements_preserved",
            "artifact_residue_free",
            "process_trace_artifact_free",
            "scope_clean",
            "hidden_check_passed",
            "transient_state_clean",
        ):
            metric_rates[metric] = round(
                100
                * sum(
                    record["correction"]["metrics"][metric]
                    and record["continuation"]["metrics"][metric]
                    for record in selected
                )
                / len(selected),
                1,
            )
        summary[condition] = {
            "runs": len(selected),
            "valid_runs": valid_runs,
            "invalid_runs": len(selected) - valid_runs,
            "artifact_deliveries": successes,
            "artifact_delivery_rate": round(100 * successes / len(selected), 1),
            "artifact_delivery_wilson_95": [round(100 * lower, 1), round(100 * upper, 1)],
            "metric_rates": metric_rates,
            "median_total_tokens": int(
                statistics.median(
                    record["total_usage"]["input_tokens"]
                    + record["total_usage"]["output_tokens"]
                    for record in selected
                )
            ),
            "median_output_tokens": int(
                statistics.median(record["total_usage"]["output_tokens"] for record in selected)
            ),
            "median_duration_seconds": round(
                statistics.median(record["total_duration_seconds"] for record in selected), 1
            ),
            "total_usage": {
                key: sum(record["total_usage"][key] for record in selected)
                for key in ("input_tokens", "cached_input_tokens", "output_tokens")
            },
            "total_duration_seconds": round(
                sum(record["total_duration_seconds"] for record in selected), 1
            ),
        }
    return summary


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
            successes = sum(record["artifact_delivery"] for record in selected)
            entry["conditions"][condition] = {
                "runs": len(selected),
                "artifact_deliveries": successes,
                "artifact_delivery_rate": round(100 * successes / len(selected), 1),
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


def summary_markdown(
    manifest: dict[str, Any],
    agent: dict[str, Any],
    gate: dict[str, Any],
    cases: list[dict[str, Any]],
    case_types: dict[str, Any],
) -> str:
    lines = [
        "# ChatterBench result",
        "",
        f"- Date: `{manifest['started_at']}`",
        f"- Host: `{manifest['host']}` / `{manifest['host_version']}`",
        f"- Model: `{manifest['model']}` at `{manifest['reasoning']}` reasoning",
        f"- Cases: `{manifest['case_count']}`; repeats: `{manifest['repeats']}`",
        f"- Repository commit: `{manifest['repository_commit']}`",
        f"- Repository dirty at start: `{str(manifest['repository_dirty']).lower()}`",
        f"- Instruction envelope: {manifest['instruction_envelope']}",
        "",
        "## Deliverable behavior",
        "",
        "| Condition | Deliverable success | Active requirements | Rejected content absent | Process labels absent | Scope correct | Median tokens | Median seconds |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for condition, values in agent.items():
        metrics = values["metric_rates"]
        interval = values["artifact_delivery_wilson_95"]
        lines.append(
            f"| {condition} | {values['artifact_deliveries']}/{values['runs']} "
            f"({values['artifact_delivery_rate']:.1f}%; 95% CI {interval[0]:.1f}–{interval[1]:.1f}) "
            f"| {metrics['active_requirements_preserved']:.1f}% "
            f"| {metrics['artifact_residue_free']:.1f}% "
            f"| {metrics['process_trace_artifact_free']:.1f}% "
            f"| {metrics['scope_clean']:.1f}% "
            f"| {values['median_total_tokens']} | {values['median_duration_seconds']:.1f} |"
        )
    lines.extend(
        [
            "",
            "## Run validity and measured cost",
            "",
            "| Condition | Valid runs | Input tokens | Cached input | Output tokens | Total agent seconds |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for condition, values in agent.items():
        usage = values["total_usage"]
        lines.append(
            f"| {condition} | {values['valid_runs']}/{values['runs']} "
            f"| {usage['input_tokens']} | {usage['cached_input_tokens']} "
            f"| {usage['output_tokens']} | {values['total_duration_seconds']:.1f} |"
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
            f"| {baseline['artifact_deliveries']}/{baseline['runs']} "
            f"| {light['artifact_deliveries']}/{light['runs']} "
            f"| {guarded['artifact_deliveries']}/{guarded['runs']} |"
        )
    lines.extend(["", "## Case-type controls", ""])
    for case_type, type_summary in case_types.items():
        rates = ", ".join(
            f"{condition} {values['artifact_deliveries']}/{values['runs']}"
            for condition, values in type_summary.items()
        )
        lines.append(f"- `{case_type}`: {rates}")
    lines.extend(
        [
            "",
            "Deliverable success is all-or-nothing across both the correction and continuation turns. "
            "It requires the current requirements and hidden checks to pass, rejected content and "
            "process labels to be absent from artifacts, file scope to stay correct, and transient "
            "state to be removed. Assistant reply wording is not scored or stored.",
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
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"output directory is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    work_root = Path(tempfile.mkdtemp(prefix="stop-chatter-agent-eval-"))

    manifest = {
        "schema_version": 2,
        "benchmark_version": "v3",
        "started_at": started_at,
        "host": "Codex CLI",
        "host_version": codex_version(args.codex_bin),
        "host_binary": args.codex_bin,
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
        "instruction_envelope": (
            "Codex system instructions plus the local account-level AGENTS.md; user config and "
            "exec policy rules disabled equally for all conditions."
        ),
        "continuation_turn": True,
        "independent_gold_visible_to_agent": False,
        "guarded_task_state_visible_to_agent": True,
        "quality_scope": "deliverables_only",
        "assistant_reply_scored": False,
        "assistant_reply_stored": False,
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    records: list[dict[str, Any]] = []
    total = manifest["planned_runs"]
    current = 0
    try:
        for repeat in range(1, args.repeats + 1):
            for case in cases:
                for condition in conditions:
                    current += 1
                    print(
                        f"RUN {current}/{total} case={case['id']} condition={condition} repeat={repeat}",
                        flush=True,
                    )
                    record = run_agent_case(
                        case=case,
                        condition=condition,
                        repeat=repeat,
                        model=args.model,
                        reasoning=args.reasoning,
                        codex_bin=args.codex_bin,
                        timeout=args.timeout,
                        work_root=work_root,
                        evidence_root=output,
                    )
                    records.append(record)
                    run_path = output / "runs" / f"{record['run']}.json"
                    run_path.parent.mkdir(parents=True, exist_ok=True)
                    run_path.write_text(
                        json.dumps(record, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8",
                    )
                    print(
                        f"DONE {record['run']} artifact_delivery={record['artifact_delivery']}",
                        flush=True,
                    )
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
        summary_markdown(manifest, agent, gate, cases_summary, case_types), encoding="utf-8"
    )
    print(f"RESULT {output / 'summary.md'}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run ChatterBench.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    gate = subparsers.add_parser("gate", help="evaluate the deterministic gate corpus")
    gate.add_argument("--output", help="optional JSON output path")
    gate.set_defaults(handler=command_gate)

    agent = subparsers.add_parser("agent", help="run paired Codex agent evaluations")
    agent.add_argument(
        "--conditions", nargs="+", default=["baseline", "light", "guarded"]
    )
    agent.add_argument("--cases", nargs="*", help="case ids; defaults to all")
    agent.add_argument("--repeats", type=int, default=3)
    agent.add_argument("--model", default="gpt-5.6-luna")
    agent.add_argument(
        "--codex-bin",
        default=shutil.which("codex") or "codex",
        help="Codex CLI executable; use the desktop-bundled binary when its cache schema is newer",
    )
    agent.add_argument("--reasoning", choices=("low", "medium", "high", "xhigh", "max"), default="medium")
    agent.add_argument("--timeout", type=int, default=300, help="seconds per turn")
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
