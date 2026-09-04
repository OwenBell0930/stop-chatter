from __future__ import annotations

import importlib.util
import re
import shutil
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("chatterbench", REPO_ROOT / "evals" / "benchmark.py")
assert SPEC and SPEC.loader
BENCHMARK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BENCHMARK)


def compile_patterns(patterns: list[str]) -> list[re.Pattern[str]]:
    return [re.compile(pattern, flags=re.IGNORECASE | re.MULTILINE) for pattern in patterns]


def strip_patterns(text: str, patterns: list[re.Pattern[str]]) -> str:
    cleaned = text
    for pattern in patterns:
        cleaned = pattern.sub("", cleaned)
    return cleaned


def copy_fixture(case: dict) -> Path:
    source = Path(case["_directory"]) / "fixture"
    destination = Path(tempfile.mkdtemp(prefix="sce1-ortho-"))
    shutil.copytree(source, destination, dirs_exist_ok=True)
    return destination


def score(root: Path, before: dict[str, bytes], case: dict) -> dict:
    return BENCHMARK.score_workspace(root, before, case, continuation=False)


def delete_path(root: Path, relative: str) -> None:
    path = root / relative
    if path.is_file():
        path.unlink()


def clean_retired(root: Path, case: dict, keep: set[str]) -> None:
    patterns = compile_patterns(case.get("retired_patterns", []))
    for path in root.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(root).as_posix()
        if relative in keep or BENCHMARK.ignored_artifact(relative):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        cleaned = strip_patterns(text, patterns)
        if cleaned != text:
            path.write_text(cleaned, encoding="utf-8")


class OrthogonalityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.cases = BENCHMARK.load_cases()
        self.addCleanup(self._cleanup)
        self._temps: list[Path] = []

    def _cleanup(self) -> None:
        for path in self._temps:
            shutil.rmtree(path, ignore_errors=True)

    def _workspace(self, case: dict) -> tuple[Path, dict[str, bytes]]:
        root = copy_fixture(case)
        self._temps.append(root)
        return root, BENCHMARK.snapshot(root)

    def test_each_case_has_orthogonality_hooks(self) -> None:
        self.assertEqual(len(self.cases), 6)
        for case in self.cases:
            spec = case["orthogonality"]
            fixture = Path(case["_directory"]) / "fixture"
            self.assertTrue((fixture / spec["residue_path"]).is_file(), case["id"])
            self.assertTrue((fixture / spec["wordless_forbidden"]).is_file(), case["id"])
            self.assertTrue((fixture / spec["protected_path"]).is_file(), case["id"])
            self.assertIn(spec["protected_path"], case["protected_paths"])
            self.assertIn(spec["wordless_forbidden"], case["forbidden_paths"])
            self.assertNotIn(spec["protected_path"], case["allowed_changed_paths"])
            self.assertTrue((fixture / spec["process_label_path"]).is_file(), case["id"])
            self.assertNotIn(spec["process_label_path"], case["forbidden_paths"], case["id"])
            forbidden_text = (fixture / spec["wordless_forbidden"]).read_text(encoding="utf-8")
            protected_text = (fixture / spec["protected_path"]).read_text(encoding="utf-8")
            for pattern in compile_patterns(
                case["retired_patterns"] + case["process_trace_patterns"]
            ):
                self.assertIsNone(pattern.search(forbidden_text), case["id"])
                self.assertIsNone(pattern.search(protected_text), case["id"])
            for relative in case["forbidden_paths"]:
                text = (fixture / relative).read_text(encoding="utf-8")
                for pattern in compile_patterns(case["process_trace_patterns"]):
                    self.assertIsNone(pattern.search(text), f"{case['id']}:{relative}")
            residue = (fixture / spec["residue_path"]).read_text(encoding="utf-8")
            self.assertIn(spec["retired_term"], residue)
            label_text = (fixture / spec["process_label_path"]).read_text(encoding="utf-8")
            self.assertTrue(
                any(
                    pattern.search(label_text)
                    for pattern in compile_patterns(case["process_trace_patterns"])
                ),
                case["id"],
            )

    def test_o1_residue_fails_surface_and_unrelated_pass(self) -> None:
        for case in self.cases:
            root, before = self._workspace(case)
            for path in case["forbidden_paths"]:
                delete_path(root, path)
            result = score(root, before, case)
            self.assertFalse(result["metrics"]["artifact_residue_free"], case["id"])
            self.assertTrue(result["metrics"]["retired_surface_removed"], case["id"])
            self.assertTrue(result["metrics"]["no_unrelated_mutation"], case["id"])

    def test_o2_surface_fails_residue_and_unrelated_pass(self) -> None:
        for case in self.cases:
            root, before = self._workspace(case)
            keep = {case["orthogonality"]["wordless_forbidden"]}
            for path in case["forbidden_paths"]:
                if path not in keep:
                    delete_path(root, path)
            clean_retired(root, case, keep)
            result = score(root, before, case)
            self.assertTrue(result["metrics"]["artifact_residue_free"], case["id"])
            self.assertFalse(result["metrics"]["retired_surface_removed"], case["id"])
            self.assertTrue(result["metrics"]["no_unrelated_mutation"], case["id"])

    def test_o3_new_file_fails_unrelated_only(self) -> None:
        for case in self.cases:
            root, before = self._workspace(case)
            for path in case["forbidden_paths"]:
                delete_path(root, path)
            clean_retired(root, case, set())
            (root / "unrelated-extra.md").write_text("helper note\n", encoding="utf-8")
            result = score(root, before, case)
            self.assertTrue(result["metrics"]["artifact_residue_free"], case["id"])
            self.assertTrue(result["metrics"]["retired_surface_removed"], case["id"])
            self.assertFalse(result["metrics"]["no_unrelated_mutation"], case["id"])
            self.assertIn("unrelated-extra.md", result["unexpected_changes"])

    def test_o4_protected_edit_fails_unrelated_only(self) -> None:
        for case in self.cases:
            root, before = self._workspace(case)
            for path in case["forbidden_paths"]:
                delete_path(root, path)
            clean_retired(root, case, set())
            protected = root / case["orthogonality"]["protected_path"]
            protected.write_text(protected.read_text(encoding="utf-8") + "\nnote\n", encoding="utf-8")
            result = score(root, before, case)
            self.assertTrue(result["metrics"]["artifact_residue_free"], case["id"])
            self.assertTrue(result["metrics"]["retired_surface_removed"], case["id"])
            self.assertFalse(result["metrics"]["no_unrelated_mutation"], case["id"])
            self.assertIn(case["orthogonality"]["protected_path"], result["protected_failures"])

    def test_o6_process_label_fails_only_h3(self) -> None:
        for case in self.cases:
            root, before = self._workspace(case)
            for path in case["forbidden_paths"]:
                delete_path(root, path)
            clean_retired(root, case, set())
            for path in root.rglob("*"):
                if not path.is_file() or path.is_symlink():
                    continue
                relative = path.relative_to(root).as_posix()
                if BENCHMARK.ignored_artifact(relative):
                    continue
                try:
                    text = path.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    continue
                cleaned = strip_patterns(text, compile_patterns(case["process_trace_patterns"]))
                if cleaned != text:
                    path.write_text(cleaned, encoding="utf-8")
            label_path = root / case["orthogonality"]["process_label_path"]
            label_path.write_text(
                label_path.read_text(encoding="utf-8")
                + "\n"
                + case["orthogonality"]["process_label"]
                + "\n",
                encoding="utf-8",
            )
            result = score(root, before, case)
            self.assertTrue(result["metrics"]["artifact_residue_free"], case["id"])
            self.assertFalse(result["metrics"]["process_trace_artifact_free"], case["id"])
            self.assertTrue(result["metrics"]["retired_surface_removed"], case["id"])
            self.assertTrue(result["metrics"]["no_unrelated_mutation"], case["id"])

    def test_o5_preservation_contract_is_required(self) -> None:
        case = BENCHMARK.load_cases(["compatibility_contract"])[0]
        root, before = self._workspace(case)
        for path in case["forbidden_paths"]:
            delete_path(root, path)
        clean_retired(root, case, set())
        (root / "tests" / "test_contract.py").unlink()
        result = score(root, before, case)
        self.assertFalse(result["metrics"]["active_requirements_preserved"])
        self.assertTrue(result["metrics"]["artifact_residue_free"])


if __name__ == "__main__":
    unittest.main()
