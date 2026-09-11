from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def invoke(tmp_path: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    home = tmp_path / "home"
    state = tmp_path / "state"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir(exist_ok=True)
    for name in ("npm", "pi"):
        command = fake_bin / name
        command.write_text("#!/bin/sh\nprintf '%s\\n' \"$0 $*\" >> \"$HARNESS_LOG\"\n")
        command.chmod(0o755)
    environment = os.environ | {
        "HOME": str(home),
        "XDG_STATE_HOME": str(state),
        "HARNESS_LOG": str(tmp_path / "commands"),
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "PYTHONPATH": str(ROOT / "src"),
    }
    return subprocess.run(
        [sys.executable, "-m", "harness_kit.cli", *arguments],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
    )


class HarnessKitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_preview_is_read_only(self) -> None:
        result = invoke(self.path, "preview")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("create", result.stdout)
        self.assertFalse((self.path / "commands").exists())
        self.assertFalse((self.path / "home").exists())

    def test_install_is_idempotent_and_owns_links(self) -> None:
        first = invoke(self.path, "install")
        self.assertEqual(first.returncode, 0, first.stderr)
        home = self.path / "home"
        self.assertTrue((home / ".claude/agents/scout.md").is_symlink())
        self.assertTrue((home / ".agents/skills/code-review").is_symlink())
        self.assertTrue((home / ".pi/agent/AGENTS.md").is_symlink())
        commands = (self.path / "commands").read_text().splitlines()
        self.assertEqual(len(commands), 2)
        state = json.loads((self.path / "state/harness-kit/state.json").read_text())
        self.assertIn(str(home.resolve() / ".pi/agent/AGENTS.md"), state["links"])

        second = invoke(self.path, "install")
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn("noop", second.stdout)

    def test_pi_agents_default_to_medium_thinking(self) -> None:
        result = invoke(self.path, "install", "--harness", "pi")
        self.assertEqual(result.returncode, 0, result.stderr)
        generated_agents = sorted((ROOT / ".generated/pi/agents").glob("*.md"))
        self.assertEqual(len(generated_agents), 5)
        for agent in generated_agents:
            self.assertIn("thinking: medium\n", agent.read_text(), agent)

    def test_scoped_install_preserves_other_harness_links(self) -> None:
        first = invoke(self.path, "install")
        self.assertEqual(first.returncode, 0, first.stderr)
        second = invoke(self.path, "install", "--harness", "pi")
        self.assertEqual(second.returncode, 0, second.stderr)
        claude_agent = self.path / "home/.claude/agents/scout.md"
        self.assertTrue(claude_agent.is_symlink())
        state = json.loads((self.path / "state/harness-kit/state.json").read_text())
        self.assertIn(str(claude_agent.parent.resolve() / claude_agent.name), state["links"])

    def test_install_refuses_foreign_destination(self) -> None:
        foreign = self.path / "home/.pi/agent/AGENTS.md"
        foreign.parent.mkdir(parents=True)
        foreign.write_text("foreign\n")
        result = invoke(self.path, "install", "--harness", "pi")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(foreign.read_text(), "foreign\n")
        self.assertFalse((self.path / "commands").exists())

    def test_install_adopts_known_legacy_pi_instruction_link(self) -> None:
        destination = self.path / "home/.pi/agent/AGENTS.md"
        destination.parent.mkdir(parents=True)
        destination.symlink_to("/Users/pcheng/dev/pi-kit/config/pi/AGENTS.md")
        result = invoke(self.path, "install", "--harness", "pi", "--adopt-legacy")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(destination.resolve(), ROOT / "harnesses/pi/AGENTS.md")


if __name__ == "__main__":
    unittest.main()
