from __future__ import annotations

import json
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


class PackageTest(unittest.TestCase):
    def test_skill_has_portable_frontmatter(self) -> None:
        text = (REPO_ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\n"))
        self.assertIn("\nname: stop-chatter\n", text)
        self.assertIn("\ndescription: ", text)
        self.assertNotIn("[TODO", text)

    def test_public_package_contains_no_generated_task_state(self) -> None:
        self.assertFalse((REPO_ROOT / ".stop-chatter" / "state.json").exists())

    def test_state_template_cannot_claim_readiness(self) -> None:
        template = json.loads(
            (REPO_ROOT / "templates" / "state.example.json").read_text(encoding="utf-8")
        )
        self.assertIs(template["ready"], False)

    def test_runtime_scripts_do_not_import_network_clients(self) -> None:
        forbidden = (
            "import requests",
            "from requests",
            "import urllib.request",
            "from urllib.request",
            "import http.client",
            "from http.client",
            "import socket",
            "from socket",
        )
        for name in ("install.py", "uninstall.py", "stop_chatter.py"):
            text = (REPO_ROOT / "scripts" / name).read_text(encoding="utf-8")
            for marker in forbidden:
                self.assertNotIn(marker, text, f"{name} contains network client: {marker}")

    def test_published_run_records_are_artifact_only(self) -> None:
        runs = (
            REPO_ROOT
            / "evals"
            / "results"
            / "2026-09-01-chatterbench-v2-r3"
            / "runs"
        )
        paths = sorted(runs.glob("*.json"))
        self.assertEqual(len(paths), 54)
        forbidden_keys = {
            "response",
            "response_sha256",
            "response_chars",
            "retired_response_hits",
            "process_trace_response_hits",
            "session_id",
        }

        def walk(value: object) -> None:
            if isinstance(value, dict):
                self.assertTrue(forbidden_keys.isdisjoint(value))
                for child in value.values():
                    walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)

        for path in paths:
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertIn("artifact_delivery", payload)
            walk(payload)

    def test_public_facade_withholds_pre_optimization_cost_numbers(self) -> None:
        forbidden = (
            "165.7k",
            "178.9k",
            "225.3k",
            "+7.9%",
            "+16.4%",
            "+35.9%",
            "+36.4%",
        )
        for name in (
            "README.md",
            "README.zh-CN.md",
            "assets/benchmark-v2.svg",
            "assets/benchmark-v2-en.svg",
            "assets/chatterbench.svg",
            "assets/chatterbench-en.svg",
            "assets/results-table.svg",
            "assets/cover.svg",
        ):
            text = (REPO_ROOT / name).read_text(encoding="utf-8")
            for marker in forbidden:
                self.assertNotIn(marker, text, f"{name} exposes stale cost number: {marker}")

    def test_public_facade_uses_current_deliverable_labels(self) -> None:
        forbidden = ("文件改动不越界", "95% CI", "Unevaluable", "无法评价")
        for name in (
            "README.md",
            "README.zh-CN.md",
            "assets/benchmark-v2.svg",
            "assets/benchmark-v2-en.svg",
            "assets/chatterbench.svg",
            "assets/results-table.svg",
            "assets/cover.svg",
        ):
            text = (REPO_ROOT / name).read_text(encoding="utf-8")
            for marker in forbidden:
                self.assertNotIn(marker, text, f"{name} exposes internal eval wording: {marker}")
        chinese = (REPO_ROOT / "README.zh-CN.md").read_text(encoding="utf-8")
        self.assertIn("33.3%", chinese)
        self.assertIn("86.7%", chinese)
        self.assertIn("96.7%", chinese)
        self.assertIn("180 次任务", chinese)
        self.assertIn("assets/cover.svg", chinese)
        self.assertIn("assets/chatterbench.svg", chinese)
        self.assertIn("assets/results-table.svg", chinese)
        self.assertIn('width="1280"', chinese)
        self.assertIn("避免多余解释和过程留痕", chinese)
        hero = (REPO_ROOT / "assets" / "cover.svg").read_text(encoding="utf-8")
        self.assertIn("解释：", hero)
        self.assertIn("PR 写成「番茄炒蛋（无东坡肉）」", hero)
        self.assertIn("方案被叫成「简洁高效不啰嗦版」", hero)
        self.assertIn("用例还在测「为什么没有东坡肉」", hero)
        self.assertIn("记下「用户不喜欢东坡肉」", hero)
        chart = (REPO_ROOT / "assets" / "chatterbench.svg").read_text(encoding="utf-8")
        self.assertIn("33.3%", chart)
        self.assertIn("86.7%", chart)
        self.assertIn("96.7%", chart)

    def test_light_benchmark_card_uses_soft_blue(self) -> None:
        source = (REPO_ROOT / "scripts" / "generate_readme_assets.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('("light", "Light", SOFT_BLUE, 450)', source)


if __name__ == "__main__":
    unittest.main()
