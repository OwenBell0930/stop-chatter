from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
GATE = REPO_ROOT / "scripts" / "stop_chatter.py"


def make_state(
    *,
    requirement_paths: list[str],
    retired: list[dict] | None = None,
    meta_constraints: list[dict] | None = None,
    exceptions: list[dict] | None = None,
) -> dict:
    return {
        "schema_version": 1,
        "ready": True,
        "active_target": {
            "goal": "Prepare the requested current artifact.",
            "requirements": [
                {
                    "id": "R1",
                    "text": "Produce the requested artifact.",
                    "paths": requirement_paths,
                }
            ],
            "meta_constraints": meta_constraints or [],
        },
        "retired": retired or [],
        "delivery": {
            "ignore_paths": [".git/**", ".stop-chatter/**"],
            "allow_process_trace_paths": [],
            "exceptions": exceptions or [],
        },
    }


class GateTest(unittest.TestCase):
    def run_gate(self, state: dict, files: dict[str, str]) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state_path = root / ".stop-chatter" / "state.json"
            state_path.parent.mkdir(parents=True)
            state_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
            for relative, content in files.items():
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
            return subprocess.run(
                [
                    sys.executable,
                    str(GATE),
                    "check",
                    "--root",
                    str(root),
                    "--format",
                    "json",
                    *files.keys(),
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

    def test_clean_current_state_passes(self) -> None:
        state = make_state(
            requirement_paths=["recipe.md"],
            retired=[
                {
                    "id": "X1",
                    "label": "东坡肉",
                    "aliases": ["东坡肘子", "酱油"],
                    "scope": "task",
                }
            ],
        )
        result = self.run_gate(state, {"recipe.md": "# 番茄炒蛋\n\n番茄、鸡蛋、盐。\n"})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_cleanup_state_on_pass_removes_state_in_same_command(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state_path = root / ".stop-chatter" / "state.json"
            state_path.parent.mkdir(parents=True)
            state_path.write_text(
                json.dumps(make_state(requirement_paths=["recipe.md"]), ensure_ascii=False),
                encoding="utf-8",
            )
            artifact = root / "recipe.md"
            artifact.write_text("# 番茄炒蛋\n", encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(GATE),
                    "check",
                    "--root",
                    str(root),
                    "--format",
                    "json",
                    "--cleanup-state-on-pass",
                    "recipe.md",
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            payload = json.loads(result.stdout)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue(payload["state_removed"])
            self.assertFalse(state_path.exists())
            self.assertTrue(artifact.is_file())

    def test_cleanup_state_on_pass_preserves_state_after_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state_path = root / ".stop-chatter" / "state.json"
            state_path.parent.mkdir(parents=True)
            state_path.write_text(
                json.dumps(
                    make_state(
                        requirement_paths=["recipe.md"],
                        retired=[
                            {"id": "X1", "label": "东坡肉", "aliases": [], "scope": "task"}
                        ],
                    ),
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (root / "recipe.md").write_text("# 东坡肉\n", encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(GATE),
                    "check",
                    "--root",
                    str(root),
                    "--format",
                    "json",
                    "--cleanup-state-on-pass",
                    "recipe.md",
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            payload = json.loads(result.stdout)
            self.assertEqual(result.returncode, 1)
            self.assertFalse(payload["state_removed"])
            self.assertTrue(state_path.is_file())

    def test_rejected_item_in_title_fails(self) -> None:
        state = make_state(
            requirement_paths=["recipe.md"],
            retired=[{"id": "X1", "label": "东坡肉", "aliases": [], "scope": "task"}],
        )
        result = self.run_gate(state, {"recipe.md": "# 番茄炒蛋（无东坡肉）\n"})
        payload = json.loads(result.stdout)
        self.assertEqual(result.returncode, 1)
        self.assertIn("STC001", {item["code"] for item in payload["violations"]})

    def test_semantic_alias_resurrection_fails(self) -> None:
        state = make_state(
            requirement_paths=["recipe.md"],
            retired=[
                {
                    "id": "X1",
                    "label": "东坡肉",
                    "aliases": ["东坡肘子"],
                    "scope": "task",
                }
            ],
        )
        result = self.run_gate(state, {"recipe.md": "最后加入东坡肘子。\n"})
        payload = json.loads(result.stdout)
        terms = {item["term"] for item in payload["violations"]}
        self.assertIn("东坡肘子", terms)

    def test_unmapped_test_file_fails(self) -> None:
        state = make_state(requirement_paths=["recipe.md"])
        result = self.run_gate(state, {"tests/test_absence.py": "def test_absence(): pass\n"})
        payload = json.loads(result.stdout)
        self.assertIn("STC002", {item["code"] for item in payload["violations"]})

    def test_meta_instruction_label_fails(self) -> None:
        state = make_state(
            requirement_paths=["README.md"],
            meta_constraints=[
                {
                    "id": "M1",
                    "text": "Keep the response concise.",
                    "leak_markers": ["简洁高效不啰嗦版"],
                }
            ],
        )
        result = self.run_gate(state, {"README.md": "# 方案2.0（简洁高效不啰嗦版）\n"})
        payload = json.loads(result.stdout)
        self.assertIn("STC003", {item["code"] for item in payload["violations"]})

    def test_narrow_active_contract_exception_passes(self) -> None:
        state = make_state(
            requirement_paths=["tests/contracts/**"],
            retired=[
                {"id": "X1", "label": "legacy-wire-token", "aliases": [], "scope": "task"}
            ],
            exceptions=[
                {
                    "path": "tests/contracts/**",
                    "codes": ["STC001"],
                    "terms": ["legacy-wire-token"],
                    "requirement_id": "R1",
                    "reason": "R1 requires rejecting this externally supplied token.",
                }
            ],
        )
        result = self.run_gate(
            state,
            {"tests/contracts/test_wire.py": "TOKEN = 'legacy-wire-token'\n"},
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_exception_must_reference_active_requirement(self) -> None:
        state = make_state(
            requirement_paths=["tests/**"],
            exceptions=[
                {
                    "path": "tests/**",
                    "codes": ["STC001"],
                    "terms": ["legacy"],
                    "requirement_id": "R404",
                    "reason": "Not active.",
                }
            ],
        )
        result = self.run_gate(state, {"tests/test_x.py": "legacy\n"})
        self.assertEqual(result.returncode, 2)
        self.assertIn("config_error", json.loads(result.stdout))

    def test_init_creates_gitignored_transient_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run(
                [sys.executable, str(GATE), "init", "--root", temporary],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            root = Path(temporary)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue((root / ".stop-chatter" / "state.json").is_file())
            self.assertEqual(
                (root / ".stop-chatter" / ".gitignore").read_text(encoding="utf-8"),
                "state.json\n",
            )
            check = subprocess.run(
                [
                    sys.executable,
                    str(GATE),
                    "check",
                    "--root",
                    temporary,
                    "--mode",
                    "all",
                    "--format",
                    "json",
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(check.returncode, 2)
            self.assertIn("state.ready", json.loads(check.stdout)["config_error"])


if __name__ == "__main__":
    unittest.main()
