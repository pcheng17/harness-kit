from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = SOURCE_ROOT / "content/skills/worktree-slots/wt.sh"
HARNESS = SOURCE_ROOT / "tests/worktree_slots/run.sh"


class WorktreeSlotsTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("git"), "git is not installed")
    def test_harness_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                ["bash", str(HARNESS), str(SCRIPT)],
                env={**os.environ, "TMPDIR": directory},
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipUnless(shutil.which("shellcheck"), "shellcheck is not installed")
    def test_script_is_shellcheck_clean(self) -> None:
        result = subprocess.run(["shellcheck", str(SCRIPT)], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
