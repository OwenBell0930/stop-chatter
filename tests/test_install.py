from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALLER = REPO_ROOT / "scripts" / "install.py"


class InstallTest(unittest.TestCase):
    def test_all_project_hosts_are_discoverable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run(
                [
                    sys.executable,
                    str(INSTALLER),
                    "--host",
                    "all",
                    "--scope",
                    "project",
                    "--target",
                    temporary,
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            root = Path(temporary)
            shared = root / ".agents" / "skills" / "stop-chatter"
            claude = root / ".claude" / "skills" / "stop-chatter"
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue((shared / "SKILL.md").is_file())
            self.assertTrue((claude / "SKILL.md").is_file())
            self.assertTrue((shared / "scripts" / "stop_chatter.py").is_file())
            self.assertTrue((shared / "LICENSE").is_file())

            installed_help = subprocess.run(
                [sys.executable, str(shared / "scripts" / "stop_chatter.py"), "--help"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(
                installed_help.returncode, 0, installed_help.stdout + installed_help.stderr
            )
            self.assertIn("Prune correction residue", installed_help.stdout)

            repeated = subprocess.run(
                [
                    sys.executable,
                    str(INSTALLER),
                    "--host",
                    "all",
                    "--scope",
                    "project",
                    "--target",
                    temporary,
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(repeated.returncode, 2)
            self.assertIn("refusing to overwrite", repeated.stderr)

    def test_dry_run_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run(
                [
                    sys.executable,
                    str(INSTALLER),
                    "--host",
                    "all",
                    "--scope",
                    "project",
                    "--target",
                    temporary,
                    "--dry-run",
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            root = Path(temporary)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertFalse((root / ".agents").exists())
            self.assertFalse((root / ".claude").exists())


if __name__ == "__main__":
    unittest.main()
