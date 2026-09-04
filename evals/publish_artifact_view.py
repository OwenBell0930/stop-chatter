#!/usr/bin/env python3
"""Rebuild public ChatterBench evidence by rescoring saved artifact trees."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def rescore_record(
    record: dict[str, Any],
    cases: dict[str, dict[str, Any]],
    trees_root: Path,
    scorer: Any,
) -> dict[str, Any]:
    case = cases.get(record["case_id"])
    if case is None:
        raise ValueError(f"unknown case_id: {record['case_id']}")
    fixture = Path(case["_directory"]) / "fixture"
    before = scorer.snapshot(fixture)
    correction_tree = trees_root / record["run"] / "correction"
    continuation_tree = trees_root / record["run"] / "continuation"
    if not correction_tree.is_dir() or not continuation_tree.is_dir():
        raise ValueError(
            f"missing per-turn trees for {record['run']}; refuse to reuse stored booleans"
        )
    correction = scorer.score_workspace(
        correction_tree, before, case, continuation=False
    )
    continuation = scorer.score_workspace(
        continuation_tree, before, case, continuation=True
    )
    correction_turn = scorer.public_turn(record.get("correction_turn", {}))
    continuation_turn = scorer.public_turn(record.get("continuation_turn", {}))
    evaluable = bool(correction_turn.get("ok") and continuation_turn.get("ok"))
    return {
        "run": record["run"],
        "case_id": record["case_id"],
        "case_type": record.get("case_type", "cleanup"),
        "condition": record["condition"],
        "repeat": record["repeat"],
        "evaluable": evaluable,
        "unevaluable_reason": record.get("unevaluable_reason")
        or scorer.unevaluable_reason(correction_turn, continuation_turn),
        "artifact_delivery": bool(
            evaluable
            and correction["artifact_success"]
            and continuation["artifact_success"]
        ),
        "correction": correction,
        "continuation": continuation,
        "correction_turn": correction_turn,
        "continuation_turn": continuation_turn,
        "total_usage": record.get("total_usage")
        or scorer.merge_usage(correction_turn.get("usage"), continuation_turn.get("usage")),
        "total_cost_usd": record.get("total_cost_usd"),
        "total_cost_usd_estimated": True,
        "total_duration_seconds": record.get("total_duration_seconds"),
        "correction_patch": record.get("correction_patch", ""),
        "continuation_patch": record.get("continuation_patch", record.get("patch", "")),
        "patch": record.get("continuation_patch", record.get("patch", "")),
        "patch_sha256": record.get("patch_sha256", ""),
        "tool_journal": record.get("tool_journal", {}),
    }


def publish(result_root: Path) -> None:
    import importlib.util

    live_spec = importlib.util.spec_from_file_location(
        "live_chatterbench_for_publish",
        Path(__file__).resolve().parent / "benchmark.py",
    )
    if live_spec is None or live_spec.loader is None:
        raise RuntimeError("cannot load evals/benchmark.py")
    live_benchmark = importlib.util.module_from_spec(live_spec)
    live_spec.loader.exec_module(live_benchmark)
    scorer = live_benchmark.load_frozen_benchmark(result_root)
    cases = {case["id"]: case for case in scorer.load_cases()}
    run_paths = sorted((result_root / "runs").glob("*.json"))
    if not run_paths:
        raise ValueError(f"no run records in {result_root}")
    records = [
        rescore_record(
            json.loads(path.read_text(encoding="utf-8")),
            cases,
            result_root / "trees",
            scorer,
        )
        for path in run_paths
    ]
    manifest = json.loads((result_root / "manifest.json").read_text(encoding="utf-8"))
    manifest.update(
        {
            "result_schema_version": 5,
            "artifact_view_version": 3,
            "quality_scope": "deliverables_only",
            "assistant_reply_scored": False,
            "assistant_reply_stored": False,
            "artifact_view_rescored_from_trees": True,
            "rescored_from_freeze": True,
            "cost_usd_estimated": True,
        }
    )
    agent = scorer.summarize_runs(records)
    case_rows = scorer.summarize_cases(records)
    case_types = scorer.summarize_case_types(records)
    summary_path = result_root / "summary.json"
    prior_gate: dict[str, Any] = {}
    if summary_path.is_file():
        prior_gate = json.loads(summary_path.read_text(encoding="utf-8")).get("gate") or {}
    if not prior_gate:
        prior_gate = {
            "corpus_samples": 0,
            "code_level": {"precision": 0.0, "recall": 0.0, "f1": 0.0},
            "binary_block_decision": {"precision": 0.0, "recall": 0.0, "f1": 0.0},
            "exact_match_rate": 0.0,
        }
    summary = {
        "manifest": manifest,
        "artifact_delivery": {
            "all_cases": agent,
            "cases": case_rows,
            "case_types": case_types,
        },
        "gate": prior_gate,
    }

    for record in records:
        path = result_root / "runs" / f"{record['run']}.json"
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (result_root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (result_root / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (result_root / "summary.md").write_text(
        scorer.summary_markdown(manifest, agent, prior_gate, case_rows, case_types),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("result_root", type=Path)
    args = parser.parse_args()
    publish(args.result_root.expanduser().resolve())
    print(f"RESCORDED from freeze snapshot and per-turn trees: {args.result_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
