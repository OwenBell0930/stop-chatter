#!/usr/bin/env python3
"""Rewrite a frozen ChatterBench result as artifact-only public evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import benchmark


def sanitize_score(score: dict[str, Any]) -> dict[str, Any]:
    previous_metrics = score.get("metrics", {})
    metrics = {
        "active_requirements_preserved": bool(
            previous_metrics.get("active_requirements_preserved", False)
        ),
        "artifact_residue_free": bool(previous_metrics.get("artifact_residue_free", False)),
        "process_trace_artifact_free": not bool(score.get("process_trace_artifact_hits", [])),
        "scope_clean": bool(previous_metrics.get("scope_clean", False)),
        "hidden_check_passed": bool(previous_metrics.get("hidden_check_passed", False)),
        "transient_state_clean": bool(previous_metrics.get("transient_state_clean", False)),
    }
    return {
        "artifact_success": all(metrics.values()),
        "metrics": metrics,
        "changed_paths": score.get("changed_paths", []),
        "required_failures": score.get("required_failures", []),
        "retired_artifact_hits": score.get("retired_artifact_hits", []),
        "process_trace_artifact_hits": score.get("process_trace_artifact_hits", []),
        "unexpected_changes": score.get("unexpected_changes", []),
        "forbidden_paths_present": score.get("forbidden_paths_present", []),
        "protected_failures": score.get("protected_failures", []),
        "hidden_check_output": score.get("hidden_check_output", ""),
        "artifact_sha256": score.get("artifact_sha256", ""),
    }


def sanitize_turn(turn: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": bool(turn.get("ok", False)),
        "returncode": turn.get("returncode", 1),
        "duration_seconds": turn.get("duration_seconds", 0.0),
        "usage": turn.get(
            "usage", {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0}
        ),
        "event_types": turn.get("event_types", []),
        "error": turn.get("error", ""),
    }


def sanitize_record(record: dict[str, Any]) -> dict[str, Any]:
    correction = sanitize_score(record["correction"])
    continuation = sanitize_score(record["continuation"])
    correction_turn = sanitize_turn(record["correction_turn"])
    continuation_turn = sanitize_turn(record["continuation_turn"])
    return {
        "run": record["run"],
        "case_id": record["case_id"],
        "case_type": record.get("case_type", "cleanup"),
        "condition": record["condition"],
        "repeat": record["repeat"],
        "artifact_delivery": bool(
            correction_turn["ok"]
            and continuation_turn["ok"]
            and correction["artifact_success"]
            and continuation["artifact_success"]
        ),
        "correction": correction,
        "continuation": continuation,
        "correction_turn": correction_turn,
        "continuation_turn": continuation_turn,
        "total_usage": record["total_usage"],
        "total_duration_seconds": record["total_duration_seconds"],
        "patch": record["patch"],
        "patch_sha256": record["patch_sha256"],
    }


def publish(result_root: Path) -> None:
    summary_path = result_root / "summary.json"
    prior_summary = json.loads(summary_path.read_text(encoding="utf-8"))
    gate = prior_summary["gate"]
    records = [
        sanitize_record(json.loads(path.read_text(encoding="utf-8")))
        for path in sorted((result_root / "runs").glob("*.json"))
    ]
    manifest = json.loads((result_root / "manifest.json").read_text(encoding="utf-8"))
    expected = int(manifest.get("planned_runs", len(records)))
    if len(records) != expected:
        raise ValueError(f"expected {expected} run records, found {len(records)}")

    manifest.update(
        {
            "result_schema_version": 2,
            "artifact_view_version": 1,
            "quality_scope": "deliverables_only",
            "assistant_reply_scored": False,
            "assistant_reply_stored": False,
            "artifact_view_derived_from_frozen_run": True,
        }
    )
    agent = benchmark.summarize_runs(records)
    cases = benchmark.summarize_cases(records)
    case_types = benchmark.summarize_case_types(records)
    summary = {
        "manifest": manifest,
        "artifact_delivery": {
            "all_cases": agent,
            "cases": cases,
            "case_types": case_types,
        },
        "gate": gate,
    }

    for record in records:
        path = result_root / "runs" / f"{record['run']}.json"
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (result_root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (result_root / "summary.md").write_text(
        benchmark.summary_markdown(manifest, agent, gate, cases, case_types), encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("result_root", type=Path)
    args = parser.parse_args()
    publish(args.result_root.expanduser().resolve())
    print(f"PUBLISHED artifact-only evidence: {args.result_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
