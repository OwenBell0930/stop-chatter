from __future__ import annotations

import importlib.util
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
        self.assertEqual(len(cases), 5)
        self.assertEqual(len({case["id"] for case in cases}), 5)
        for case in cases:
            for key in ("retired_patterns", "process_trace_patterns"):
                for pattern in case[key]:
                    __import__("re").compile(pattern)
            fixture = Path(case["_directory"]) / "fixture"
            for requirement in case["requirements"]:
                self.assertTrue((fixture / requirement["path"]).is_file())

    def test_gate_corpus_exposes_known_limits(self) -> None:
        result = BENCHMARK.evaluate_gate_corpus()
        self.assertEqual(result["corpus_samples"], 20)
        self.assertLess(result["code_level"]["recall"], 100.0)
        self.assertLess(result["code_level"]["precision"], 100.0)
        self.assertGreater(result["code_level"]["f1"], 0.0)

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
                root, before, case, "Current result is ready.", continuation=False
            )
            self.assertTrue(clean["clean_success"])
            (root / "extra.md").write_text("retired concise edition\n", encoding="utf-8")
            dirty = BENCHMARK.score_workspace(
                root, before, case, "Current result is ready.", continuation=False
            )
            self.assertFalse(dirty["clean_success"])
            self.assertFalse(dirty["metrics"]["artifact_residue_free"])
            self.assertFalse(dirty["metrics"]["scope_clean"])

    def test_standard_test_caches_are_not_artifacts(self) -> None:
        self.assertTrue(BENCHMARK.ignored_artifact(".pytest_cache/README.md"))
        self.assertTrue(BENCHMARK.ignored_artifact("tests/__pycache__/test_x.pyc"))
        self.assertFalse(BENCHMARK.ignored_artifact("tests/test_x.py"))

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
