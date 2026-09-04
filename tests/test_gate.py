from __future__ import annotations

import json
import os
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
    must_remove: list[str] | None = None,
    baseline: dict | None = None,
) -> dict:
    state = {
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
            "must_remove": must_remove or [],
            "exceptions": exceptions or [],
        },
    }
    if baseline is not None:
        state["baseline"] = baseline
    return state


def run_git(root: Path, *arguments: str) -> None:
    result = subprocess.run(
        ["git", "-C", str(root), *arguments],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(result.stdout + result.stderr)


def init_git_repo(root: Path) -> None:
    run_git(root, "init")
    run_git(root, "config", "user.email", "stop-chatter-test@example.com")
    run_git(root, "config", "user.name", "Stop Chatter Test")
    run_git(root, "config", "commit.gpgsign", "false")


def write_text(root: Path, relative: str, content: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def run_cli(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(GATE), *arguments, "--root", str(root)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def payload_of(result: subprocess.CompletedProcess[str]) -> dict:
    return json.loads(result.stdout)


def codes_of(payload: dict) -> set[str]:
    return {item["code"] for item in payload.get("violations", [])}


def write_ready_state(root: Path, **kwargs) -> Path:
    state_path = root / ".stop-chatter" / "state.json"
    existing = json.loads(state_path.read_text(encoding="utf-8")) if state_path.is_file() else {}
    state = make_state(**kwargs)
    if "baseline" in existing and "baseline" not in state:
        state["baseline"] = existing["baseline"]
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    return state_path


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

    def test_file_operations_and_must_remove(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            init_git_repo(root)
            app = write_text(root, "app.py", "print('ok')\n")
            leftover = write_text(root, "leftover.txt", "neutral leftover\n")
            run_git(root, "add", "-A")
            run_git(root, "commit", "-m", "start")

            created = run_cli(root, "init")
            self.assertEqual(created.returncode, 0, created.stdout + created.stderr)
            write_ready_state(
                root,
                requirement_paths=["app.py"],
                must_remove=["leftover.txt"],
            )
            app_before = app.read_text(encoding="utf-8")
            leftover_before = leftover.read_text(encoding="utf-8")

            still_present = run_cli(root, "check", "--format", "json")
            present_payload = payload_of(still_present)
            self.assertEqual(still_present.returncode, 1, still_present.stdout)
            self.assertIn("STC006", codes_of(present_payload))
            self.assertTrue(leftover.is_file())
            self.assertEqual(leftover.read_text(encoding="utf-8"), leftover_before)
            self.assertEqual(app.read_text(encoding="utf-8"), app_before)

            leftover.unlink()
            authorized_extra = run_cli(root, "check", "--format", "json")
            self.assertEqual(
                authorized_extra.returncode, 0, authorized_extra.stdout + authorized_extra.stderr
            )
            self.assertFalse(leftover.exists())
            self.assertTrue(app.is_file())
            self.assertEqual(app.read_text(encoding="utf-8"), app_before)

            app.unlink()
            mapped_deleted = run_cli(root, "check", "--format", "json")
            mapped_payload = payload_of(mapped_deleted)
            self.assertEqual(mapped_deleted.returncode, 1, mapped_deleted.stdout)
            self.assertIn("STC005", codes_of(mapped_payload))
            self.assertFalse(app.exists())
            self.assertFalse(leftover.exists())

            write_ready_state(
                root,
                requirement_paths=["app.py"],
                must_remove=["leftover.txt", "app.py"],
            )
            authorized = run_cli(root, "check", "--format", "json")
            self.assertEqual(authorized.returncode, 0, authorized.stdout + authorized.stderr)
            self.assertFalse(app.exists())
            self.assertFalse(leftover.exists())

            globbed = write_ready_state(
                root,
                requirement_paths=["app.py"],
                must_remove=["**/*.txt"],
            )
            glob_result = run_cli(root, "check", "--format", "json")
            self.assertEqual(glob_result.returncode, 2, glob_result.stdout)
            self.assertIn("exact path", payload_of(glob_result)["config_error"])
            globbed.write_text(
                json.dumps(
                    make_state(
                        requirement_paths=["app.py"],
                        must_remove=["../secret.txt"],
                        baseline=json.loads(globbed.read_text(encoding="utf-8")).get("baseline"),
                    )
                ),
                encoding="utf-8",
            )
            escaped = run_cli(root, "check", "--format", "json")
            self.assertEqual(escaped.returncode, 2, escaped.stdout)
            self.assertIn("..", payload_of(escaped)["config_error"])

    def test_start_baseline_and_limited_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            init_git_repo(root)
            write_text(root, "app.py", "print('committed')\n")
            run_git(root, "add", "app.py")
            run_git(root, "commit", "-m", "start")
            write_text(root, "app.py", "print('user dirty')\n")
            write_text(root, "scratch.txt", "user scratch\n")

            created = run_cli(root, "init")
            self.assertEqual(created.returncode, 0, created.stdout + created.stderr)
            write_ready_state(root, requirement_paths=["app.py"])

            untouched = run_cli(root, "check", "--format", "json")
            untouched_payload = payload_of(untouched)
            self.assertEqual(untouched.returncode, 0, untouched.stdout + untouched.stderr)
            self.assertEqual(untouched_payload["coverage"], "git-baseline")
            self.assertNotIn("STC002", codes_of(untouched_payload))
            self.assertNotIn("STC005", codes_of(untouched_payload))

            write_text(root, "scratch.txt", "user scratch\nchanged this round\n")
            extra_edit = run_cli(root, "check", "--format", "json")
            extra_payload = payload_of(extra_edit)
            self.assertEqual(extra_edit.returncode, 1, extra_edit.stdout)
            self.assertIn("STC002", codes_of(extra_payload))

            write_text(root, "scratch.txt", "user scratch\n")
            Path(root / "app.py").unlink()
            deleted_original = run_cli(root, "check", "--format", "json")
            deleted_payload = payload_of(deleted_original)
            self.assertEqual(deleted_original.returncode, 1, deleted_original.stdout)
            self.assertIn("STC005", codes_of(deleted_payload))

            write_text(root, "app.py", "print('user dirty')\n")
            write_text(root, "new_unmapped.py", "print('new')\n")
            new_file = run_cli(root, "check", "--format", "json")
            new_payload = payload_of(new_file)
            self.assertEqual(new_file.returncode, 1, new_file.stdout)
            self.assertIn("STC002", codes_of(new_payload))
            self.assertIn("new_unmapped.py", {item["path"] for item in new_payload["violations"]})

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_text(root, "app.py", "print('ok')\n")
            write_ready_state(root, requirement_paths=["app.py"])
            limited = subprocess.run(
                [
                    sys.executable,
                    str(GATE),
                    "check",
                    "--root",
                    str(root),
                    "--format",
                    "json",
                    "app.py",
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            limited_payload = payload_of(limited)
            self.assertEqual(limited.returncode, 0, limited.stdout + limited.stderr)
            self.assertEqual(limited_payload["coverage"], "limited")
            self.assertIn("does not verify", limited_payload["coverage_note"])
            self.assertIn("original user changes", limited_payload["coverage_note"])

        with tempfile.TemporaryDirectory() as outside_dir:
            outside = write_text(Path(outside_dir), "secret.txt", "retired-token\n")
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                os.symlink(outside, root / "link.py")
                write_ready_state(
                    root,
                    requirement_paths=["link.py"],
                    retired=[
                        {
                            "id": "X1",
                            "label": "retired-token",
                            "aliases": [],
                            "scope": "task",
                        }
                    ],
                )
                linked = subprocess.run(
                    [
                        sys.executable,
                        str(GATE),
                        "check",
                        "--root",
                        str(root),
                        "--format",
                        "json",
                        "link.py",
                    ],
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                )
                linked_payload = payload_of(linked)
                self.assertEqual(linked.returncode, 0, linked.stdout + linked.stderr)
                self.assertNotIn("STC001", codes_of(linked_payload))
                self.assertEqual(outside.read_text(encoding="utf-8"), "retired-token\n")

    def test_narrow_exception_does_not_cover_other_paths(self) -> None:
        state = make_state(
            requirement_paths=["tests/contracts/**", "README.md"],
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
            {
                "tests/contracts/test_wire.py": "TOKEN = 'legacy-wire-token'\n",
                "README.md": "Do not send legacy-wire-token in docs.\n",
            },
        )
        payload = payload_of(result)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertEqual(
            {(item["code"], item["path"]) for item in payload["violations"]},
            {("STC001", "README.md")},
        )

    def test_state_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            init_git_repo(root)
            write_text(root, "app.py", "print('ok')\n")
            run_git(root, "add", "app.py")
            run_git(root, "commit", "-m", "start")
            write_text(root, "app.py", "print('dirty')\n")
            cache = write_text(root, "__pycache__/keep.pyc", "cache")
            other_user = write_text(root, "notes.txt", "keep me\n")

            first = run_cli(root, "init")
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            state_path = root / ".stop-chatter" / "state.json"
            ignore_path = root / ".stop-chatter" / ".gitignore"
            original = state_path.read_text(encoding="utf-8")
            original_payload = json.loads(original)
            self.assertFalse(original_payload["ready"])
            self.assertEqual(original_payload["baseline"]["coverage"], "git")
            self.assertIn("app.py", original_payload["baseline"]["preexisting"])

            second = run_cli(root, "init")
            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
            self.assertIn("Reusing", second.stdout)
            self.assertEqual(state_path.read_text(encoding="utf-8"), original)

            write_ready_state(root, requirement_paths=["app.py"])
            filled = state_path.read_text(encoding="utf-8")
            third = run_cli(root, "init")
            self.assertEqual(third.returncode, 0, third.stdout + third.stderr)
            self.assertEqual(state_path.read_text(encoding="utf-8"), filled)
            self.assertEqual(
                json.loads(filled)["baseline"]["git_head"],
                original_payload["baseline"]["git_head"],
            )

            passed = run_cli(root, "check", "--format", "json", "--cleanup-state-on-pass")
            passed_payload = payload_of(passed)
            self.assertEqual(passed.returncode, 0, passed.stdout + passed.stderr)
            self.assertTrue(passed_payload["state_removed"])
            self.assertFalse(state_path.exists())
            self.assertTrue(ignore_path.is_file())
            self.assertEqual(cache.read_text(encoding="utf-8"), "cache")
            self.assertEqual(other_user.read_text(encoding="utf-8"), "keep me\n")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            created = run_cli(root, "init")
            self.assertEqual(created.returncode, 0, created.stdout + created.stderr)
            unfilled = run_cli(root, "check", "--format", "json", "--mode", "all")
            self.assertEqual(unfilled.returncode, 2, unfilled.stdout)
            self.assertIn("state.ready", payload_of(unfilled)["config_error"])

            write_ready_state(
                root,
                requirement_paths=["app.py"],
                retired=[{"id": "X1", "label": "gone", "aliases": [], "scope": "task"}],
            )
            write_text(root, "app.py", "gone\n")
            failed = run_cli(
                root, "check", "--format", "json", "--mode", "all", "--cleanup-state-on-pass"
            )
            failed_payload = payload_of(failed)
            self.assertEqual(failed.returncode, 1, failed.stdout)
            self.assertFalse(failed_payload["state_removed"])
            self.assertTrue((root / ".stop-chatter" / "state.json").is_file())

            foreign = json.loads((root / ".stop-chatter" / "state.json").read_text(encoding="utf-8"))
            foreign.setdefault("baseline", {})
            foreign["baseline"]["root"] = str(Path(temporary).resolve() / "other")
            (root / ".stop-chatter" / "state.json").write_text(
                json.dumps(foreign), encoding="utf-8"
            )
            reused = run_cli(root, "init")
            self.assertEqual(reused.returncode, 2, reused.stdout + reused.stderr)
            self.assertIn("different root", reused.stderr)

            (root / ".stop-chatter" / "state.json").write_text("{not-json", encoding="utf-8")
            invalid = run_cli(root, "init")
            self.assertEqual(invalid.returncode, 2, invalid.stdout + invalid.stderr)
            self.assertIn("refusing to reuse or overwrite", invalid.stderr)

    def test_hidden_must_remove_path_keeps_leading_dot(self) -> None:
        hidden_names = (".retired.md", ".cache.dat")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            init_git_repo(root)
            write_text(root, "app.py", "print('ok')\n")
            for name in hidden_names:
                write_text(root, name, "stale hidden file\n")
            write_text(root, "retired.md", "plain sibling\n")
            run_git(root, "add", "-A")
            run_git(root, "commit", "-m", "start")

            created = run_cli(root, "init")
            self.assertEqual(created.returncode, 0, created.stdout + created.stderr)

            write_ready_state(
                root,
                requirement_paths=["app.py"],
                must_remove=["retired.md"],
            )
            sibling_only = run_cli(root, "check", "--format", "json")
            sibling_payload = payload_of(sibling_only)
            self.assertEqual(sibling_only.returncode, 1, sibling_only.stdout)
            self.assertEqual(
                {(item["code"], item["path"]) for item in sibling_payload["violations"]},
                {("STC006", "retired.md")},
            )
            for name in hidden_names:
                self.assertTrue((root / name).is_file())

            write_ready_state(
                root,
                requirement_paths=["app.py"],
                must_remove=[hidden_names[0], "./" + hidden_names[1]],
            )
            still_present = run_cli(root, "check", "--format", "json")
            present_payload = payload_of(still_present)
            self.assertEqual(still_present.returncode, 1, still_present.stdout)
            self.assertEqual(codes_of(present_payload), {"STC006"})
            self.assertEqual(
                {item["path"] for item in present_payload["violations"]},
                set(hidden_names),
            )
            self.assertEqual(present_payload["checked_files"], 0)
            for name in hidden_names:
                self.assertTrue((root / name).is_file())

            write_ready_state(
                root,
                requirement_paths=["app.py"],
                must_remove=["../" + hidden_names[0]],
            )
            escaped_result = run_cli(root, "check", "--format", "json")
            self.assertEqual(escaped_result.returncode, 2, escaped_result.stdout)
            self.assertIn("..", payload_of(escaped_result)["config_error"])
            write_ready_state(
                root,
                requirement_paths=["app.py"],
                must_remove=list(hidden_names),
            )

            for name in hidden_names:
                (root / name).unlink()
            removed = run_cli(root, "check", "--format", "json")
            removed_payload = payload_of(removed)
            self.assertEqual(removed.returncode, 0, removed.stdout + removed.stderr)
            self.assertNotIn("STC006", codes_of(removed_payload))
            for name in hidden_names:
                self.assertFalse((root / name).exists())

    def test_complete_baseline_still_content_checks_explicit_and_dirty_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            init_git_repo(root)
            write_text(root, "deliverable.md", "contains retired-token\n")
            write_text(root, "notes.md", "user dirty retired-token\n")
            write_text(root, "clean.md", "fresh text\n")
            run_git(root, "add", "deliverable.md", "clean.md")
            run_git(root, "commit", "-m", "start")

            created = run_cli(root, "init")
            self.assertEqual(created.returncode, 0, created.stdout + created.stderr)
            write_ready_state(
                root,
                requirement_paths=["deliverable.md", "notes.md", "clean.md"],
                retired=[
                    {"id": "X1", "label": "retired-token", "aliases": [], "scope": "task"}
                ],
            )

            explicit = run_cli(root, "check", "--format", "json", "deliverable.md")
            explicit_payload = payload_of(explicit)
            self.assertEqual(explicit.returncode, 1, explicit.stdout)
            self.assertGreaterEqual(explicit_payload["checked_files"], 1)
            self.assertIn(
                ("STC001", "deliverable.md"),
                {(item["code"], item["path"]) for item in explicit_payload["violations"]},
            )
            self.assertNotIn("STC002", codes_of(explicit_payload))

            dirty = run_cli(root, "check", "--format", "json")
            dirty_payload = payload_of(dirty)
            self.assertEqual(dirty.returncode, 1, dirty.stdout)
            self.assertIn(
                ("STC001", "notes.md"),
                {(item["code"], item["path"]) for item in dirty_payload["violations"]},
            )
            self.assertNotIn("STC002", codes_of(dirty_payload))

            write_text(root, "deliverable.md", "cleaned up\n")
            write_text(root, "notes.md", "user dirty cleaned\n")
            cleaned = run_cli(root, "check", "--format", "json", "deliverable.md", "clean.md")
            cleaned_payload = payload_of(cleaned)
            self.assertEqual(cleaned.returncode, 0, cleaned.stdout + cleaned.stderr)
            self.assertGreaterEqual(cleaned_payload["checked_files"], 1)
            self.assertNotIn("STC001", codes_of(cleaned_payload))
            self.assertNotIn("STC002", codes_of(cleaned_payload))

    def test_restored_user_deleted_file_is_this_round_change(self) -> None:
        original = "# old feature\nkept as committed\n"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            init_git_repo(root)
            write_text(root, "main.md", "# main\n")
            write_text(root, "old-feature.md", original)
            run_git(root, "add", "-A")
            run_git(root, "commit", "-m", "start")
            (root / "old-feature.md").unlink()

            created = run_cli(root, "init")
            self.assertEqual(created.returncode, 0, created.stdout + created.stderr)
            write_ready_state(root, requirement_paths=["main.md"])

            left_deleted = run_cli(root, "check", "--format", "json")
            left_payload = payload_of(left_deleted)
            self.assertEqual(left_deleted.returncode, 0, left_deleted.stdout + left_deleted.stderr)
            self.assertNotIn("STC002", codes_of(left_payload))
            self.assertNotIn("STC005", codes_of(left_payload))

            write_text(root, "old-feature.md", original)
            restored = run_cli(root, "check", "--format", "json")
            restored_payload = payload_of(restored)
            self.assertEqual(restored.returncode, 1, restored.stdout)
            self.assertIn("STC002", codes_of(restored_payload))
            self.assertIn(
                "old-feature.md",
                {item["path"] for item in restored_payload["violations"]},
            )

            write_ready_state(root, requirement_paths=["main.md", "old-feature.md"])
            authorized = run_cli(root, "check", "--format", "json")
            self.assertEqual(authorized.returncode, 0, authorized.stdout + authorized.stderr)

    def test_directory_symlink_is_not_read_for_content_or_digest(self) -> None:
        outside_marker = "outside-only-retired-token"
        with tempfile.TemporaryDirectory() as outside_dir:
            outside = Path(outside_dir)
            write_text(outside, "data.md", f"{outside_marker}\n")
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                os.symlink(outside, root / "linked-dir")
                write_text(root, "inside.md", f"{outside_marker}\n")
                write_ready_state(
                    root,
                    requirement_paths=["linked-dir/data.md", "inside.md", "link.py"],
                    retired=[
                        {
                            "id": "X1",
                            "label": outside_marker,
                            "aliases": [],
                            "scope": "task",
                        }
                    ],
                )

                linked = run_cli(root, "check", "--format", "json", "linked-dir/data.md")
                linked_payload = payload_of(linked)
                self.assertNotEqual(linked.returncode, 0, linked.stdout)
                self.assertNotIn("STC001", codes_of(linked_payload))
                if linked.returncode == 2:
                    self.assertIn("config_error", linked_payload)
                else:
                    self.assertIn("STC004", codes_of(linked_payload))
                    self.assertEqual(linked_payload["checked_files"], 0)
                self.assertEqual((outside / "data.md").read_text(encoding="utf-8"), f"{outside_marker}\n")

                inside = run_cli(root, "check", "--format", "json", "inside.md")
                inside_payload = payload_of(inside)
                self.assertEqual(inside.returncode, 1, inside.stdout)
                self.assertIn("STC001", codes_of(inside_payload))
                self.assertGreaterEqual(inside_payload["checked_files"], 1)

                os.symlink(outside / "data.md", root / "link.py")
                file_link = run_cli(root, "check", "--format", "json", "link.py")
                file_link_payload = payload_of(file_link)
                self.assertEqual(file_link.returncode, 0, file_link.stdout + file_link.stderr)
                self.assertNotIn("STC001", codes_of(file_link_payload))


if __name__ == "__main__":
    unittest.main()
