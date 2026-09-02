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
        ):
            text = (REPO_ROOT / name).read_text(encoding="utf-8")
            for marker in forbidden:
                self.assertNotIn(marker, text, f"{name} exposes stale cost number: {marker}")

    def test_light_benchmark_card_uses_soft_blue(self) -> None:
        source = (REPO_ROOT / "scripts" / "generate_readme_assets.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('("light", "Light", SOFT_BLUE, 450)', source)


if __name__ == "__main__":
    unittest.main()
