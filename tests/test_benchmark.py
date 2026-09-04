from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("chatterbench", REPO_ROOT / "evals" / "benchmark.py")
assert SPEC and SPEC.loader
BENCHMARK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BENCHMARK)


class BenchmarkTest(unittest.TestCase):
    def test_all_case_specs_load(self) -> None:
        cases = BENCHMARK.load_cases()
        self.assertEqual(len(cases), 6)
        self.assertEqual(len({case["id"] for case in cases}), 6)
        self.assertEqual(
            {case["case_type"] for case in cases}, {"cleanup", "preservation_control"}
        )
        for case in cases:
            for key in ("retired_patterns", "process_trace_patterns"):
                for pattern in case[key]:
                    __import__("re").compile(pattern)
            fixture = Path(case["_directory"]) / "fixture"
            for requirement in case["requirements"]:
                self.assertTrue((fixture / requirement["path"]).is_file())

    def test_preservation_control_has_narrow_guard_exceptions(self) -> None:
        case = BENCHMARK.load_cases(["compatibility_contract"])[0]
        state = BENCHMARK.make_guard_state(case)
        exceptions = state["delivery"]["exceptions"]
        self.assertEqual(len(exceptions), 3)
        self.assertTrue(all(item["requirement_id"] == "R1" for item in exceptions))
        files = {"README.md": b'validate_token("  value  ")  # returns "value"\n'}
        self.assertEqual(
            BENCHMARK.requirement_failures(files, case["continuation_requirements"]), []
        )

    def test_condition_prompt_names_mode_only(self) -> None:
        light = BENCHMARK.condition_prompt("light", {"prompt": "Do the task."})
        guarded = BENCHMARK.condition_prompt("guarded", {"prompt": "Do the task."})
        self.assertIn("Light mode", light)
        self.assertIn("Guarded mode", guarded)
        self.assertIn("Do the task.", guarded)
        self.assertNotIn("$stop-chatter", light)
        self.assertNotIn("$stop-chatter", guarded)
        self.assertNotIn("--cleanup-state-on-pass", guarded)
        self.assertNotIn("state.json", guarded)

    def test_condition_schedule_rotates(self) -> None:
        order = ["baseline", "light", "guarded"]
        self.assertEqual(
            BENCHMARK.schedule_conditions(order, repeat=1, case_index=0),
            ["baseline", "light", "guarded"],
        )
        self.assertEqual(
            BENCHMARK.schedule_conditions(order, repeat=2, case_index=0),
            ["light", "guarded", "baseline"],
        )

    def test_parse_grok_missing_usage_is_unknown(self) -> None:
        parsed = BENCHMARK.parse_grok_payload(
            '{"sessionId":"abc","stopReason":"stop","num_turns":2}'
        )
        self.assertEqual(parsed["session_id"], "abc")
        self.assertIsNone(parsed["usage"]["input_tokens"])
        self.assertIsNone(parsed["usage"]["cached_input_tokens"])
        self.assertIsNone(parsed["usage"]["output_tokens"])
        self.assertIsNone(parsed["cost_usd"])
        self.assertEqual(parsed["num_turns"], 2)

    def test_parse_grok_keeps_zero_and_does_not_fold_cache_into_input(self) -> None:
        parsed = BENCHMARK.parse_grok_payload(
            json.dumps(
                {
                    "usage": {
                        "input_tokens": 0,
                        "cache_read_input_tokens": 9,
                        "output_tokens": 4,
                    },
                    "total_cost_usd": 0.0,
                    "modelUsage": {"grok-4.6-build": {}},
                }
            )
        )
        self.assertEqual(parsed["usage"]["input_tokens"], 0)
        self.assertEqual(parsed["usage"]["cached_input_tokens"], 9)
        self.assertEqual(parsed["usage"]["output_tokens"], 4)
        self.assertEqual(parsed["cost_usd"], 0.0)
        self.assertEqual(parsed["model_slug"], "grok-4.6-build")

    def test_gate_corpus_exposes_known_limits(self) -> None:
        result = BENCHMARK.evaluate_gate_corpus()
        self.assertEqual(result["corpus_samples"], 20)
        self.assertLess(result["code_level"]["recall"], 100.0)
        self.assertLess(result["code_level"]["precision"], 100.0)
        self.assertGreater(result["code_level"]["f1"], 0.0)

    def test_grok_command_uses_headless_json(self) -> None:
        command = BENCHMARK.build_grok_command(
            grok_bin="grok",
            prompt="continue",
            model="grok-4.6",
            reasoning="medium",
            cwd=Path("/tmp/chatterbench-fixture"),
            session_id="01a0602f-e86f-74b1-8f27-0ae0b8902089",
        )
        self.assertEqual(command[0], "grok")
        self.assertIn("--output-format", command)
        self.assertIn("json", command)
        self.assertIn("grok-4.6", command)
        self.assertIn("--resume", command)
        self.assertIn("01a0602f-e86f-74b1-8f27-0ae0b8902089", command)

    def test_codebuddy_command_uses_headless_json(self) -> None:
        command = BENCHMARK.build_codebuddy_command(
            codebuddy_bin="codebuddy",
            prompt="continue",
            model="glm-5",
            reasoning="medium",
            session_id="cfde1a68-bbfd-403f-a890-89cc65c2bc3a",
        )
        self.assertEqual(command[0], "codebuddy")
        self.assertIn("--output-format", command)
        self.assertIn("json", command)
        self.assertIn("glm-5", command)
        self.assertIn("--resume", command)
        self.assertIn("cfde1a68-bbfd-403f-a890-89cc65c2bc3a", command)
        self.assertNotIn("WebFetch", command[command.index("--tools") + 1].split(","))

    def test_parse_codebuddy_payload_reads_result_and_actual_slug(self) -> None:
        parsed = BENCHMARK.parse_codebuddy_payload(
            json.dumps(
                [
                    {
                        "type": "message",
                        "role": "assistant",
                        "providerData": {
                            "model": "glm-5.3",
                            "requestModelId": "custom-local:glm-5",
                        },
                    },
                    {
                        "type": "result",
                        "subtype": "success",
                        "session_id": "sess-1",
                        "is_error": False,
                        "num_turns": 2,
                        "total_cost_usd": 0,
                        "usage": {
                            "input_tokens": 10,
                            "cache_read_input_tokens": 3,
                            "output_tokens": 4,
                        },
                    },
                ]
            )
        )
        self.assertEqual(parsed["session_id"], "sess-1")
        self.assertEqual(parsed["usage"]["input_tokens"], 10)
        self.assertEqual(parsed["usage"]["cached_input_tokens"], 3)
        self.assertEqual(parsed["usage"]["output_tokens"], 4)
        self.assertIsNone(parsed["cost_usd"])
        self.assertEqual(parsed["model_slug"], "glm-5.3")
        self.assertEqual(parsed["stop_reason"], "success")
        self.assertEqual(parsed["num_turns"], 2)

    def test_codebuddy_skill_copy_is_ignored_by_artifact_scan(self) -> None:
        self.assertTrue(BENCHMARK.ignored_artifact(".codebuddy/skills/stop-chatter/SKILL.md"))

    def test_metrics_split_residue_from_unrelated_file(self) -> None:
        case = {
            "requirements": [{"path": "result.md", "contains": ["Current result"]}],
            "continuation_requirements": [],
            "retired_patterns": ["retired"],
            "process_trace_patterns": ["concise edition"],
            "allowed_changed_paths": ["result.md"],
            "forbidden_paths": ["tests/test_no_x.py"],
            "protected_paths": ["keep.md"],
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "result.md").write_text("Current result\n", encoding="utf-8")
            (root / "keep.md").write_text("stable\n", encoding="utf-8")
            before = BENCHMARK.snapshot(root)
            residue_only = BENCHMARK.score_workspace(root, before, case, continuation=False)
            self.assertTrue(residue_only["metrics"]["retired_surface_removed"])
            self.assertTrue(residue_only["metrics"]["no_unrelated_mutation"])
            (root / "result.md").write_text("Current result retired\n", encoding="utf-8")
            residue = BENCHMARK.score_workspace(root, before, case, continuation=False)
            self.assertFalse(residue["metrics"]["artifact_residue_free"])
            self.assertTrue(residue["metrics"]["retired_surface_removed"])
            self.assertTrue(residue["metrics"]["no_unrelated_mutation"])
            (root / "result.md").write_text("Current result\n", encoding="utf-8")
            (root / "extra.md").write_text("helper\n", encoding="utf-8")
            unrelated = BENCHMARK.score_workspace(root, before, case, continuation=False)
            self.assertTrue(unrelated["metrics"]["artifact_residue_free"])
            self.assertFalse(unrelated["metrics"]["no_unrelated_mutation"])
            self.assertTrue(unrelated["metrics"]["retired_surface_removed"])

    def test_score_requires_positive_result_and_clean_scope(self) -> None:
        case = {
            "requirements": [{"path": "result.md", "contains": ["Current result"]}],
            "continuation_requirements": [],
            "retired_patterns": ["retired"],
            "process_trace_patterns": ["concise edition"],
            "allowed_changed_paths": ["result.md"],
            "forbidden_paths": [],
            "protected_paths": [],
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "result.md").write_text("Old result\n", encoding="utf-8")
            before = BENCHMARK.snapshot(root)
            (root / "result.md").write_text("Current result\n", encoding="utf-8")
            clean = BENCHMARK.score_workspace(
                root, before, case, continuation=False
            )
            self.assertTrue(clean["artifact_success"])
            (root / ".stop-chatter").mkdir()
            (root / ".stop-chatter" / "state.json").write_text("{}\n", encoding="utf-8")
            leftover_state = BENCHMARK.score_workspace(
                root, before, case, continuation=False
            )
            self.assertTrue(leftover_state["artifact_success"])
            self.assertFalse(leftover_state["metrics"]["transient_state_clean"])
            (root / "extra.md").write_text("retired concise edition\n", encoding="utf-8")
            dirty = BENCHMARK.score_workspace(
                root, before, case, continuation=False
            )
            self.assertFalse(dirty["artifact_success"])
            self.assertFalse(dirty["metrics"]["artifact_residue_free"])
            self.assertFalse(dirty["metrics"]["process_trace_artifact_free"])
            self.assertFalse(dirty["metrics"]["scope_clean"])

    def test_standard_test_caches_are_not_artifacts(self) -> None:
        self.assertTrue(BENCHMARK.ignored_artifact(".pytest_cache/README.md"))
        self.assertTrue(BENCHMARK.ignored_artifact("tests/__pycache__/test_x.pyc"))
        self.assertFalse(BENCHMARK.ignored_artifact("tests/test_x.py"))

    def test_public_turn_retains_cost_but_not_reply_or_session(self) -> None:
        turn = {
            "ok": True,
            "returncode": 0,
            "duration_seconds": 1.0,
            "usage": {"input_tokens": 2, "cached_input_tokens": 1, "output_tokens": 3},
            "response": "Current result.",
            "session_id": "private-session",
            "event_types": ["turn.completed"],
            "error": "",
            "model_slug": "grok-4.6-build",
            "cost_usd": 0.02,
            "num_turns": 3,
            "stop_reason": "stop",
            "thought": "hidden",
        }
        public = BENCHMARK.public_turn(turn)
        self.assertEqual(public["usage"]["input_tokens"], 2)
        self.assertEqual(public["num_turns"], 3)
        self.assertEqual(public["stop_reason"], "stop")
        self.assertTrue(public["cost_usd_estimated"])
        self.assertNotIn("response", public)
        self.assertNotIn("response_sha256", public)
        self.assertNotIn("response_chars", public)
        self.assertNotIn("session_id", public)
        self.assertNotIn("thought", public)

    def test_resume_places_exec_only_options_before_subcommand(self) -> None:
        command = BENCHMARK.build_codex_command(
            codex_bin="codex",
            prompt="continue",
            model="gpt-5.6-luna",
            reasoning="medium",
            cwd=Path("/tmp/chatterbench-fixture"),
            session_id="00000000-0000-0000-0000-000000000000",
        )
        self.assertLess(command.index("--color"), command.index("resume"))
        self.assertLess(command.index("--sandbox"), command.index("resume"))
        self.assertLess(command.index("--cd"), command.index("resume"))
        self.assertIn("/tmp/chatterbench-fixture", command)
        self.assertGreater(command.index("--json"), command.index("resume"))


if __name__ == "__main__":
    unittest.main()
