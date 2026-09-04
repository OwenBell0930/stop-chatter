from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("chatterbench", REPO_ROOT / "evals" / "benchmark.py")
assert SPEC and SPEC.loader
BENCHMARK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BENCHMARK)

PUBLISH_SPEC = importlib.util.spec_from_file_location(
    "publish_artifact_view", REPO_ROOT / "evals" / "publish_artifact_view.py"
)
assert PUBLISH_SPEC and PUBLISH_SPEC.loader
PUBLISH = importlib.util.module_from_spec(PUBLISH_SPEC)
PUBLISH_SPEC.loader.exec_module(PUBLISH)


def fake_metrics(*, success: bool = True, leftover_state: bool = False) -> dict:
    return {
        "active_requirements_preserved": success,
        "artifact_residue_free": success,
        "process_trace_artifact_free": success,
        "retired_surface_removed": success,
        "no_unrelated_mutation": success,
        "scope_clean": success,
        "hidden_check_passed": success,
        "transient_state_clean": not leftover_state,
    }


def fake_turn(*, ok: bool = True, usage: dict | None = None) -> dict:
    return BENCHMARK.public_turn(
        {
            "ok": ok,
            "returncode": 0 if ok else 1,
            "duration_seconds": 1.5 if ok else None,
            "usage": usage
            or {"input_tokens": 4, "cached_input_tokens": 2, "output_tokens": 3},
            "event_types": ["grok.headless"],
            "error": "",
            "model_slug": "grok-4.6-build",
            "cost_usd": 0.01 if ok else None,
            "num_turns": 2 if ok else None,
            "stop_reason": "stop" if ok else "error",
        }
    )


def fake_record(
    *,
    condition: str = "baseline",
    success: bool = True,
    evaluable: bool = True,
    usage: dict | None = None,
    duration: float | None = 3.0,
    cost: float | None = 0.02,
) -> dict:
    metrics = fake_metrics(success=success)
    turn = fake_turn(
        ok=evaluable,
        usage=usage
        if usage is not None
        else {"input_tokens": 4, "cached_input_tokens": 2, "output_tokens": 3},
    )
    if not evaluable:
        turn = fake_turn(ok=False, usage=BENCHMARK.EMPTY_USAGE)
    return {
        "run": f"recipe_cleanup__{condition}__r1",
        "case_id": "recipe_cleanup",
        "case_type": "cleanup",
        "condition": condition,
        "repeat": 1,
        "evaluable": evaluable,
        "unevaluable_reason": "" if evaluable else "correction_timeout",
        "artifact_delivery": bool(success and evaluable),
        "correction": {"artifact_success": success, "metrics": metrics},
        "continuation": {"artifact_success": success, "metrics": metrics},
        "correction_turn": turn,
        "continuation_turn": turn,
        "total_usage": usage
        if usage is not None
        else BENCHMARK.merge_usage(turn["usage"], turn["usage"]),
        "total_cost_usd": cost if evaluable else None,
        "total_duration_seconds": duration if evaluable else None,
        "tool_journal": {"counts": {"checker_init": 0, "checker_check": 0, "checker_cleanup_flag": 0}, "events": []},
    }


def write_complete_run(output: Path, run_name: str, case_id: str, condition: str, repeat: int) -> dict:
    (output / "trees" / run_name / "correction").mkdir(parents=True, exist_ok=True)
    (output / "trees" / run_name / "continuation").mkdir(parents=True, exist_ok=True)
    (output / "trees" / run_name / "correction" / "keep.txt").write_text("c\n", encoding="utf-8")
    (output / "trees" / run_name / "continuation" / "keep.txt").write_text("k\n", encoding="utf-8")
    (output / "patches").mkdir(parents=True, exist_ok=True)
    (output / "patches" / f"{run_name}.correction.patch").write_text("diff a\n", encoding="utf-8")
    (output / "patches" / f"{run_name}.continuation.patch").write_text("diff b\n", encoding="utf-8")
    record = fake_record(condition=condition, success=True, evaluable=True)
    record.update(
        {
            "run": run_name,
            "case_id": case_id,
            "repeat": repeat,
            "correction_patch": f"patches/{run_name}.correction.patch",
            "continuation_patch": f"patches/{run_name}.continuation.patch",
            "patch": f"patches/{run_name}.continuation.patch",
            "patch_sha256": "abc",
        }
    )
    path = output / "runs" / f"{run_name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return record


def agent_args(output: Path) -> argparse.Namespace:
    return argparse.Namespace(
        cases=["recipe_cleanup"],
        conditions=["baseline", "light", "guarded"],
        repeats=1,
        model="grok-4.6",
        reasoning="medium",
        grok_bin="mock-grok",
        timeout=5,
        output=str(output),
        keep_workspaces=False,
    )


class CalibrationTest(unittest.TestCase):
    def test_prepare_workspace_does_not_prefill_guarded_state(self) -> None:
        case = BENCHMARK.load_cases(["recipe_cleanup"])[0]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "ws"
            BENCHMARK.prepare_workspace(case, root, "guarded")
            self.assertFalse((root / ".stop-chatter" / "state.json").exists())
            self.assertTrue(
                (root / ".agents" / "skills" / "stop-chatter" / "SKILL.md").is_file()
            )
            self.assertTrue(
                (root / ".codebuddy" / "skills" / "stop-chatter" / "SKILL.md").is_file()
            )
            self.assertNotIn("must_remove", (root / "recipe.md").read_text(encoding="utf-8"))

    def test_prepare_workspace_records_leftover_origin_in_git(self) -> None:
        case = BENCHMARK.load_cases(["recipe_cleanup"])[0]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "ws"
            BENCHMARK.prepare_workspace(case, root, "baseline")
            log = BENCHMARK.run_command(["git", "log", "--pretty=%s"], cwd=root, timeout=30)
            self.assertIn(BENCHMARK.PRODUCT_COMMIT, log.stdout)
            self.assertIn(BENCHMARK.LEFTOVER_COMMIT, log.stdout)
            first = BENCHMARK.run_command(
                ["git", "ls-tree", "-r", "--name-only", "HEAD~1"], cwd=root, timeout=30
            )
            head = BENCHMARK.run_command(
                ["git", "ls-tree", "-r", "--name-only", "HEAD"], cwd=root, timeout=30
            )
            self.assertNotIn("RELEASE.md", first.stdout.splitlines())
            self.assertNotIn("tests/test_no_pork.py", first.stdout.splitlines())
            self.assertIn("RELEASE.md", head.stdout.splitlines())
            self.assertIn("tests/test_no_pork.py", head.stdout.splitlines())
            self.assertIn("shopping-list.md", first.stdout.splitlines())
            self.assertIn("上一轮超范围草稿遗留", (root / "RELEASE.md").read_text(encoding="utf-8"))
            self.assertNotIn("forbidden_paths", (root / "RELEASE.md").read_text(encoding="utf-8"))

    def test_continuation_prompt_is_ordinary_follow_up(self) -> None:
        for case in BENCHMARK.load_cases():
            prompt = case["continuation_prompt"]
            self.assertNotIn("Guarded", prompt)
            self.assertNotIn("Light mode", prompt)
            self.assertNotIn("$stop-chatter", prompt)
            self.assertNotIn("stop_chatter.py", prompt)
            self.assertNotIn("--cleanup-state-on-pass", prompt)
            self.assertNotIn("must_remove", prompt)
            self.assertNotIn("forbidden_paths", prompt)

    def test_run_agent_case_saves_both_turns_without_session(self) -> None:
        case = BENCHMARK.load_cases(["recipe_cleanup"])[0]
        calls: list[dict] = []

        def fake_grok_turn(**kwargs):
            calls.append(kwargs)
            cwd = kwargs["cwd"]
            turn = "continuation" if kwargs.get("session_id") else "correction"
            marker = (cwd / ".stop-chatter" / "eval-turn").read_text(encoding="utf-8").strip()
            self.assertEqual(marker, turn)
            log = cwd / ".stop-chatter" / "tool-log.jsonl"
            log.parent.mkdir(parents=True, exist_ok=True)
            with log.open("a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {
                            "kind": "checker",
                            "turn": turn,
                            "command": "init" if turn == "correction" else "check",
                            "argv": ["init"] if turn == "correction" else ["check"],
                            "exit_code": 0,
                            "duration_ms": 4,
                        }
                    )
                    + "\n"
                )
            return {
                "ok": True,
                "returncode": 0,
                "duration_seconds": 0.2,
                "error": "",
                "session_id": kwargs.get("session_id") or "internal-session",
                "usage": {"input_tokens": 5, "cached_input_tokens": 7, "output_tokens": 3},
                "event_types": ["grok.headless"],
                "model_slug": "grok-4.6-build",
                "cost_usd": 0.003,
                "stop_reason": "stop",
                "num_turns": 2,
                "thought": "do not store",
                "response": "Current result.",
            }

        with tempfile.TemporaryDirectory() as temporary:
            work_root = Path(temporary) / "work"
            evidence = Path(temporary) / "out"
            work_root.mkdir()
            evidence.mkdir()
            with mock.patch.object(BENCHMARK, "grok_turn", side_effect=fake_grok_turn):
                record = BENCHMARK.run_agent_case(
                    case=case,
                    condition="baseline",
                    repeat=1,
                    model="grok-4.6",
                    reasoning="medium",
                    grok_bin="mock-grok",
                    timeout=5,
                    work_root=work_root,
                    evidence_root=evidence,
                )
            self.assertEqual(len(calls), 2)
            self.assertIsNone(calls[0].get("session_id"))
            self.assertEqual(calls[1]["session_id"], "internal-session")
            self.assertNotIn("Guarded", calls[1]["prompt"])
            dumped = json.dumps(record)
            self.assertNotIn("internal-session", dumped)
            self.assertNotIn("do not store", dumped)
            self.assertNotIn("Current result.", dumped)
            self.assertTrue((evidence / "trees" / record["run"] / "correction").is_dir())
            self.assertTrue((evidence / "trees" / record["run"] / "continuation").is_dir())
            self.assertTrue((evidence / "patches" / f"{record['run']}.correction.patch").is_file())
            self.assertTrue((evidence / "patches" / f"{record['run']}.continuation.patch").is_file())
            turns = {event["turn"] for event in record["tool_journal"]["events"]}
            self.assertEqual(turns, {"correction", "continuation"})
            self.assertEqual(record["correction_turn"]["num_turns"], 2)
            self.assertEqual(record["total_usage"]["cached_input_tokens"], 14)
            self.assertEqual(record["total_usage"]["input_tokens"], 10)
            self.assertTrue(record["evaluable"])

    def test_summarize_counts_attempts_successes_and_unevaluable(self) -> None:
        records = [
            fake_record(condition="baseline", success=True, evaluable=True),
            fake_record(condition="baseline", success=False, evaluable=True),
            fake_record(condition="baseline", success=False, evaluable=False, usage=BENCHMARK.EMPTY_USAGE),
        ]
        records[1]["run"] = "recipe_cleanup__baseline__r2"
        records[2]["run"] = "recipe_cleanup__baseline__r3"
        summary = BENCHMARK.summarize_runs(records)["baseline"]
        self.assertEqual(summary["attempted"], 3)
        self.assertEqual(summary["artifact_deliveries"], 1)
        self.assertEqual(summary["evaluable"], 2)
        self.assertEqual(summary["unevaluable"], 1)
        self.assertEqual(summary["artifact_delivery_rate"], 33.3)
        self.assertEqual(summary["artifact_delivery_rate_evaluable"], 50.0)

    def test_summarize_missing_tokens_stay_unknown(self) -> None:
        records = [
            fake_record(
                condition="light",
                usage={"input_tokens": None, "cached_input_tokens": 2, "output_tokens": 3},
                duration=None,
                cost=None,
            )
        ]
        summary = BENCHMARK.summarize_runs(records)["light"]
        self.assertIsNone(summary["total_usage"]["input_tokens"])
        self.assertEqual(summary["total_usage"]["cached_input_tokens"], 2)
        self.assertEqual(summary["total_usage"]["output_tokens"], 3)
        self.assertIsNone(summary["total_estimated_usd"])
        self.assertIsNone(summary["total_duration_seconds"])
        self.assertIsNone(summary["median_total_tokens"])

    def test_merge_usage_does_not_add_cache_into_input(self) -> None:
        merged = BENCHMARK.merge_usage(
            {"input_tokens": 4, "cached_input_tokens": 10, "output_tokens": 2},
            {"input_tokens": 6, "cached_input_tokens": 1, "output_tokens": 3},
        )
        self.assertEqual(merged["input_tokens"], 10)
        self.assertEqual(merged["cached_input_tokens"], 11)
        self.assertEqual(merged["output_tokens"], 5)

    def test_summary_markdown_has_absolute_cost_not_percent_overhead(self) -> None:
        records = [fake_record(condition=name) for name in ("baseline", "light", "guarded")]
        summary = BENCHMARK.summarize_runs(records)
        cases = BENCHMARK.summarize_cases(records)
        types = BENCHMARK.summarize_case_types(records)
        gate = {
            "corpus_samples": 20,
            "code_level": {"precision": 1.0, "recall": 1.0, "f1": 1.0},
            "binary_block_decision": {"precision": 1.0, "recall": 1.0, "f1": 1.0},
            "exact_match_rate": 1.0,
        }
        text = BENCHMARK.summary_markdown(
            {
                "started_at": "2026-09-03T00:00:00+00:00",
                "host": "Grok Build CLI",
                "host_version": "mock",
                "model": "grok-4.6",
                "reasoning": "medium",
                "case_count": 1,
                "repeats": 1,
                "repository_commit": "deadbeef",
                "repository_dirty": True,
                "instruction_envelope": "test",
                "freeze": {"files": {"SKILL.md": "abc"}},
            },
            summary,
            gate,
            cases,
            types,
        )
        self.assertIn("SCE-1.2", text)
        self.assertIn("Attempts", text)
        self.assertIn("Unevaluable", text)
        self.assertIn("Estimated USD", text)
        self.assertIn("estimate", text.lower())
        self.assertNotIn("overhead", text.lower())
        self.assertNotIn("Developer ledger", text)
        self.assertNotRegex(text, r"[+-]\d+\.\d+%")

    def test_freeze_verify_rejects_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            meta = BENCHMARK.write_freeze(output)
            self.assertIn("evals/benchmark.py", meta["files"])
            self.assertIn("SKILL.md", meta["files"])
            BENCHMARK.verify_freeze(output / "freeze")
            target = output / "freeze" / "evals" / "benchmark.py"
            target.write_text(target.read_text(encoding="utf-8") + "\n# drift\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "freeze drift"):
                BENCHMARK.verify_freeze(output / "freeze")

    def test_publish_refuses_without_freeze(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "runs").mkdir()
            (root / "manifest.json").write_text("{}\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "freeze"):
                PUBLISH.publish(root)

    def test_publish_rescored_from_freeze_not_live(self) -> None:
        case = BENCHMARK.load_cases(["recipe_cleanup"])[0]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            BENCHMARK.write_freeze(root)
            run_name = "recipe_cleanup__baseline__r1"
            fixture = Path(case["_directory"]) / "fixture"
            for turn in ("correction", "continuation"):
                dest = root / "trees" / run_name / turn
                shutil.copytree(fixture, dest)
                (dest / "recipe.md").write_text(
                    dest.joinpath("recipe.md").read_text(encoding="utf-8") + "\n鸡蛋嫩、番茄出汁\n",
                    encoding="utf-8",
                )
            record = fake_record(condition="baseline", success=True, evaluable=True)
            record["run"] = run_name
            (root / "runs").mkdir()
            (root / "runs" / f"{run_name}.json").write_text(
                json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            (root / "manifest.json").write_text(
                json.dumps(
                    {
                        "started_at": "2026-09-03T00:00:00+00:00",
                        "host": "Grok Build CLI",
                        "host_version": "mock",
                        "model": "grok-4.6",
                        "reasoning": "medium",
                        "case_count": 1,
                        "repeats": 1,
                        "repository_commit": "deadbeef",
                        "repository_dirty": True,
                        "instruction_envelope": "test",
                        "planned_runs": 1,
                        "freeze": {"files": {"SKILL.md": "abc"}},
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (root / "summary.json").write_text("{}\n", encoding="utf-8")
            frozen_scorer = root / "freeze" / "evals" / "benchmark.py"
            frozen_scorer.write_text(
                frozen_scorer.read_text(encoding="utf-8").replace(
                    '"artifact_success": artifact_success,',
                    '"artifact_success": True,  # freeze-test-marker',
                    1,
                ),
                encoding="utf-8",
            )
            meta = json.loads((root / "freeze" / "freeze.json").read_text(encoding="utf-8"))
            meta["files"]["evals/benchmark.py"] = BENCHMARK.sha256_bytes(frozen_scorer.read_bytes())
            (root / "freeze" / "freeze.json").write_text(
                json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )

            def boom(*args, **kwargs):
                raise AssertionError("live scorer must not be used")

            with mock.patch.object(BENCHMARK, "score_workspace", side_effect=boom):
                PUBLISH.publish(root)
            saved = json.loads((root / "runs" / f"{run_name}.json").read_text(encoding="utf-8"))
            self.assertTrue(saved["correction"]["artifact_success"])
            self.assertTrue(saved["continuation"]["artifact_success"])
            self.assertNotIn("session_id", json.dumps(saved))
            drifted = root / "freeze" / "evals" / "cases" / "recipe_cleanup" / "case.json"
            drifted.write_text(drifted.read_text(encoding="utf-8").replace("recipe.md", "recipe.md"), encoding="utf-8")
            drifted.write_text(drifted.read_text(encoding="utf-8") + "\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "freeze drift"):
                PUBLISH.publish(root)

    def test_checkpoint_skips_complete_and_does_not_retry_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            BENCHMARK.write_freeze(output)
            complete = write_complete_run(
                output, "recipe_cleanup__baseline__r1", "recipe_cleanup", "baseline", 1
            )
            self.assertEqual(BENCHMARK.run_record_status(output, complete["run"]), "complete")
            (output / "runs" / "recipe_cleanup__light__r1.json").parent.mkdir(
                parents=True, exist_ok=True
            )
            (output / "runs" / "recipe_cleanup__light__r1.json").write_text(
                json.dumps({"run": "recipe_cleanup__light__r1", "case_id": "recipe_cleanup"})
                + "\n",
                encoding="utf-8",
            )
            (output / "runs" / "recipe_cleanup__guarded__r1.json").write_text(
                json.dumps({"run": "recipe_cleanup__guarded__r1", "case_id": "recipe_cleanup"})
                + "\n",
                encoding="utf-8",
            )
            self.assertEqual(
                BENCHMARK.run_record_status(output, "recipe_cleanup__light__r1"),
                "incomplete",
            )
            grok_calls: list[str] = []

            def fake_grok_turn(**kwargs):
                grok_calls.append(kwargs["prompt"])
                raise AssertionError("must not call the model for complete or incomplete records")

            with mock.patch.object(BENCHMARK, "grok_turn", side_effect=fake_grok_turn):
                with mock.patch.object(BENCHMARK, "grok_version", return_value="mock"):
                    with self.assertRaisesRegex(RuntimeError, "first condition group"):
                        BENCHMARK.command_agent(agent_args(output))
            self.assertEqual(grok_calls, [])

    def test_checkpoint_skips_complete_records_on_same_freeze(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            BENCHMARK.write_freeze(output)
            for condition in ("baseline", "light", "guarded"):
                write_complete_run(
                    output,
                    f"recipe_cleanup__{condition}__r1",
                    "recipe_cleanup",
                    condition,
                    1,
                )
            grok_calls = []

            def fake_grok_turn(**kwargs):
                grok_calls.append(1)
                raise AssertionError("complete records must not be retried")

            with mock.patch.object(BENCHMARK, "grok_turn", side_effect=fake_grok_turn):
                with mock.patch.object(BENCHMARK, "grok_version", return_value="mock"):
                    code = BENCHMARK.command_agent(agent_args(output))
            self.assertEqual(code, 0)
            self.assertEqual(grok_calls, [])
            text = (output / "summary.md").read_text(encoding="utf-8")
            self.assertIn("Attempts", text)
            self.assertNotIn("overhead", text.lower())


if __name__ == "__main__":
    unittest.main()
