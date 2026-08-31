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


if __name__ == "__main__":
    unittest.main()
