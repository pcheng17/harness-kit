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
        common = ROOT / "content/instructions/AGENTS.md"
        for destination in (
            home / ".claude/CLAUDE.md",
            home / ".agents/AGENTS.md",
            home / ".pi/agent/AGENTS.md",
        ):
            self.assertTrue(destination.is_symlink(), destination)
            self.assertEqual(destination.resolve(), common)
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
        self.assertEqual((self.path / "home/.claude/CLAUDE.md").resolve(), ROOT / "content/instructions/AGENTS.md")
        state = json.loads((self.path / "state/harness-kit/state.json").read_text())
        self.assertIn(str(claude_agent.parent.resolve() / claude_agent.name), state["links"])

    def test_scoped_install_deploys_only_requested_common_locations(self) -> None:
        claude = invoke(self.path, "install", "--harness", "claude")
        self.assertEqual(claude.returncode, 0, claude.stderr)
        home = self.path / "home"
        self.assertTrue((home / ".claude/CLAUDE.md").is_symlink())
        self.assertFalse((home / ".agents/AGENTS.md").exists())
        self.assertFalse((home / ".pi/agent/AGENTS.md").exists())

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            pi = invoke(path, "install", "--harness", "pi")
            self.assertEqual(pi.returncode, 0, pi.stderr)
            pi_home = path / "home"
            self.assertFalse((pi_home / ".claude/CLAUDE.md").exists())
            self.assertTrue((pi_home / ".agents/AGENTS.md").is_symlink())
            self.assertTrue((pi_home / ".pi/agent/AGENTS.md").is_symlink())

    def test_install_does_not_claim_matching_unmanaged_instruction_link(self) -> None:
        destination = self.path / "home/.agents/AGENTS.md"
        destination.parent.mkdir(parents=True)
        destination.symlink_to(ROOT / "content/instructions/AGENTS.md")
        result = invoke(self.path, "install", "--harness", "pi")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(destination.resolve(), ROOT / "content/instructions/AGENTS.md")
        state = json.loads((self.path / "state/harness-kit/state.json").read_text())
        self.assertNotIn(str(destination.parent.resolve() / destination.name), state["links"])

    def test_install_refuses_foreign_common_instruction_destinations(self) -> None:
        destinations = (
            ("claude", ".claude/CLAUDE.md"),
            ("pi", ".agents/AGENTS.md"),
            ("pi", ".pi/agent/AGENTS.md"),
        )
        for harness, relative_destination in destinations:
            with self.subTest(destination=relative_destination):
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory)
                    foreign = path / "home" / relative_destination
                    foreign.parent.mkdir(parents=True)
                    foreign.write_text("foreign\n")
                    result = invoke(path, "install", "--harness", harness)
                    self.assertEqual(result.returncode, 2)
                    self.assertEqual(foreign.read_text(), "foreign\n")
                    self.assertFalse((path / "commands").exists())

    def test_install_skip_unblocks_other_destinations(self) -> None:
        destination = self.path / "home/.claude/CLAUDE.md"
        destination.parent.mkdir(parents=True)
        foreign = self.path / "dotfiles/CLAUDE.md"
        foreign.parent.mkdir(parents=True)
        foreign.write_text("foreign\n")
        destination.symlink_to(foreign)
        result = invoke(self.path, "install", "--harness", "claude", "--skip", str(destination))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("skip", result.stdout)
        self.assertEqual(destination.resolve(), foreign)
        self.assertTrue((self.path / "home/.claude/agents/scout.md").is_symlink())
        state = json.loads((self.path / "state/harness-kit/state.json").read_text())
        self.assertNotIn(str(destination.resolve()), state["links"])

    def test_install_adopts_known_legacy_pi_instruction_link(self) -> None:
        destination = self.path / "home/.pi/agent/AGENTS.md"
        destination.parent.mkdir(parents=True)
        legacy = self.path / "home/dev/pi-kit/config/pi/AGENTS.md"
        legacy.parent.mkdir(parents=True)
        legacy.write_text("legacy\n")
        destination.symlink_to(legacy)
        result = invoke(self.path, "install", "--harness", "pi", "--adopt-legacy")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(destination.resolve(), ROOT / "content/instructions/AGENTS.md")


if __name__ == "__main__":
    unittest.main()
