from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

SOURCE_ROOT = Path(__file__).resolve().parents[1]
REAL_HOME = Path.home().resolve()


@dataclass(frozen=True)
class Sandbox:
    root: Path
    project: Path

    @property
    def mutation_roots(self) -> tuple[Path, ...]:
        return (
            # TemporaryDirectory itself is the only cleanup/deletion root;
            # every test-created path below is a descendant of it.
            self.root,
            self.project,
            self.root / "home",
            self.root / "codex-home",
            self.root / "xdg/state",
            self.root / "xdg/config",
            self.root / "xdg/cache",
            self.root / "xdg/data",
            self.root / "tmp",
            self.root / "npm/cache",
            self.root / "npm/prefix",
            self.root / "npm/config",
            self.root / "pi",
            self.root / "git",
        )

    def assert_contained(self) -> None:
        root = self.root.resolve()
        source_root = SOURCE_ROOT.resolve()
        if self.project.resolve() == source_root:
            raise RuntimeError("sandbox project must differ from source checkout")
        for path in self.mutation_roots:
            resolved = path.resolve()
            if not resolved.is_relative_to(root):
                raise RuntimeError(f"sandbox mutation root escapes TemporaryDirectory: {resolved}")
            if resolved == REAL_HOME or resolved.is_relative_to(REAL_HOME):
                raise RuntimeError(f"sandbox mutation root touches real HOME: {resolved}")
            if resolved == source_root or source_root.is_relative_to(resolved):
                raise RuntimeError(f"sandbox mutation root contains source checkout: {resolved}")

    def prepare_environment(self) -> None:
        self.assert_contained()
        (self.root / "tmp").mkdir(parents=True)
        self.assert_contained()


def create_sandbox(root: Path) -> Sandbox:
    sandbox = Sandbox(root=root, project=root / "project")
    sandbox.assert_contained()
    shutil.copytree(
        SOURCE_ROOT,
        sandbox.project,
        ignore=shutil.ignore_patterns(".git", ".generated", ".venv", "__pycache__", ".pytest_cache", "node_modules"),
    )
    sandbox.prepare_environment()
    return sandbox


@contextmanager
def temporary_sandbox() -> Iterator[Sandbox]:
    with tempfile.TemporaryDirectory() as directory:
        yield create_sandbox(Path(directory))


def invoke(sandbox: Sandbox, *arguments: str) -> subprocess.CompletedProcess[str]:
    # Containment proof: every directory the test or CLI can mutate is under
    # this freshly-created TemporaryDirectory, never real HOME or the source.
    sandbox.assert_contained()
    fake_bin = sandbox.root / "bin"
    fake_bin.mkdir(exist_ok=True)
    for name in ("npm", "pi"):
        command = fake_bin / name
        command.write_text("#!/bin/sh\nprintf '%s|%s %s\\n' \"$PWD\" \"$0\" \"$*\" >> \"$HARNESS_LOG\"\n")
        command.chmod(0o755)
    environment = {
        "HOME": str(sandbox.root / "home"),
        "CODEX_HOME": str(sandbox.root / "codex-home"),
        "XDG_STATE_HOME": str(sandbox.root / "xdg/state"),
        "XDG_CONFIG_HOME": str(sandbox.root / "xdg/config"),
        "XDG_CACHE_HOME": str(sandbox.root / "xdg/cache"),
        "XDG_DATA_HOME": str(sandbox.root / "xdg/data"),
        "TMPDIR": str(sandbox.root / "tmp"),
        "NPM_CONFIG_USERCONFIG": str(sandbox.root / "npm/config/npmrc"),
        "NPM_CONFIG_CACHE": str(sandbox.root / "npm/cache"),
        "NPM_CONFIG_PREFIX": str(sandbox.root / "npm/prefix"),
        "PI_HOME": str(sandbox.root / "pi"),
        "GIT_CONFIG_GLOBAL": str(sandbox.root / "git/global"),
        "GIT_CONFIG_SYSTEM": str(sandbox.root / "git/system"),
        "GIT_CONFIG_NOSYSTEM": "1",
        "PATH": str(fake_bin),
        "PYTHONPATH": str(sandbox.project / "src"),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "HARNESS_LOG": str(sandbox.root / "commands"),
    }
    cwd = sandbox.project.resolve()
    if not cwd.is_relative_to(sandbox.root.resolve()) or cwd == SOURCE_ROOT.resolve():
        raise RuntimeError("CLI subprocess must run from sandbox project")
    if environment["PYTHONPATH"] != str(sandbox.project / "src"):
        raise RuntimeError("CLI subprocess must import from sandbox project")
    return subprocess.run(
        [sys.executable, "-m", "harness_kit.cli", *arguments],
        cwd=cwd,
        env=environment,
        text=True,
        capture_output=True,
    )


class HarnessKitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.sandbox = create_sandbox(Path(self.temp.name))
        self.path = self.sandbox.root
        self.project = self.sandbox.project

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_preview_is_read_only(self) -> None:
        result = invoke(self.sandbox, "preview")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("[CREATE]", result.stdout)
        self.assertIn(str(self.project), result.stdout)
        self.assertFalse((self.path / "commands").exists())
        self.assertFalse((self.path / "home").exists())

    def test_install_is_idempotent_and_owns_links(self) -> None:
        first = invoke(self.sandbox, "install")
        self.assertEqual(first.returncode, 0, first.stderr)
        home = self.path / "home"
        self.assertTrue((home / ".claude/agents/scout.md").is_symlink())
        self.assertTrue((home / ".agents/skills/code-review").is_symlink())
        common = self.project / "content/instructions/AGENTS.md"
        for destination in (home / ".claude/CLAUDE.md", home / ".agents/AGENTS.md", home / ".pi/agent/AGENTS.md"):
            self.assertTrue(destination.is_symlink(), destination)
            self.assertEqual(destination.resolve(), common)
        commands = (self.path / "commands").read_text().splitlines()
        self.assertEqual(len(commands), 2)
        self.assertTrue(all(line.startswith(f"{self.project}|") for line in commands), commands)
        state = json.loads((self.path / "xdg/state/harness-kit/state.json").read_text())
        self.assertIn(str(home.resolve() / ".pi/agent/AGENTS.md"), state["links"])
        second = invoke(self.sandbox, "install")
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn("[NOOP]", second.stdout)

    def test_skills_only_installs_only_skill_links(self) -> None:
        preview = invoke(self.sandbox, "preview", "--component", "skills")
        self.assertEqual(preview.returncode, 0, preview.stderr)
        self.assertIn(".claude/skills/code-review", preview.stdout)
        self.assertNotIn(".claude/agents/", preview.stdout)
        self.assertNotIn("AGENTS.md", preview.stdout)
        result = invoke(self.sandbox, "install", "--component", "skills")
        self.assertEqual(result.returncode, 0, result.stderr)
        home = self.path / "home"
        self.assertTrue((home / ".claude/skills/code-review").is_symlink())
        self.assertTrue((home / ".agents/skills/code-review").is_symlink())
        self.assertFalse((home / ".claude/agents/scout.md").exists())
        self.assertFalse((home / ".claude/CLAUDE.md").exists())
        self.assertFalse((home / ".agents/AGENTS.md").exists())
        self.assertFalse((self.path / "commands").exists())
        check = invoke(self.sandbox, "check", "--component", "skills")
        self.assertEqual(check.returncode, 0, check.stderr)

    def test_agents_only_gates_pi_commands_by_harness(self) -> None:
        claude = invoke(self.sandbox, "install", "--harness", "claude", "--component", "agents")
        self.assertEqual(claude.returncode, 0, claude.stderr)
        self.assertTrue((self.path / "home/.claude/agents/scout.md").is_symlink())
        self.assertFalse((self.path / "home/.claude/CLAUDE.md").exists())
        self.assertFalse((self.path / "commands").exists())
        with temporary_sandbox() as sandbox:
            pi = invoke(sandbox, "install", "--harness", "pi", "--component", "agents")
            self.assertEqual(pi.returncode, 0, pi.stderr)
            self.assertFalse((sandbox.root / "home/.agents/AGENTS.md").exists())
            self.assertEqual(len((sandbox.root / "commands").read_text().splitlines()), 2)

    def test_instructions_only_installs_only_instruction_links(self) -> None:
        result = invoke(self.sandbox, "install", "--component", "instructions")
        self.assertEqual(result.returncode, 0, result.stderr)
        home = self.path / "home"
        self.assertTrue((home / ".claude/CLAUDE.md").is_symlink())
        self.assertTrue((home / ".agents/AGENTS.md").is_symlink())
        self.assertTrue((home / ".pi/agent/AGENTS.md").is_symlink())
        self.assertFalse((home / ".claude/skills/code-review").exists())
        self.assertFalse((home / ".claude/agents/scout.md").exists())
        self.assertFalse((self.path / "commands").exists())

    def test_repeated_components_compose(self) -> None:
        result = invoke(self.sandbox, "install", "--harness", "claude", "--component", "skills", "--component", "instructions")
        self.assertEqual(result.returncode, 0, result.stderr)
        home = self.path / "home"
        self.assertTrue((home / ".claude/skills/code-review").is_symlink())
        self.assertTrue((home / ".claude/CLAUDE.md").is_symlink())
        self.assertFalse((home / ".claude/agents/scout.md").exists())

    def test_component_scoped_install_preserves_unselected_owned_links(self) -> None:
        self.assertEqual(invoke(self.sandbox, "install").returncode, 0)
        second = invoke(self.sandbox, "install", "--component", "skills")
        self.assertEqual(second.returncode, 0, second.stderr)
        agent = self.path / "home/.claude/agents/scout.md"
        self.assertTrue(agent.is_symlink())
        self.assertTrue((self.path / "home/.claude/CLAUDE.md").is_symlink())
        state = json.loads((self.path / "xdg/state/harness-kit/state.json").read_text())
        self.assertIn(str(agent.parent.resolve() / agent.name), state["links"])

    def test_pi_agents_default_to_medium_thinking(self) -> None:
        result = invoke(self.sandbox, "install", "--harness", "pi")
        self.assertEqual(result.returncode, 0, result.stderr)
        generated_agents = sorted((self.project / ".generated/pi/agents").glob("*.md"))
        self.assertEqual(len(generated_agents), 5)
        for agent in generated_agents:
            self.assertIn("thinking: medium\n", agent.read_text(), agent)

    def test_scoped_install_preserves_other_harness_links(self) -> None:
        self.assertEqual(invoke(self.sandbox, "install").returncode, 0)
        second = invoke(self.sandbox, "install", "--harness", "pi")
        self.assertEqual(second.returncode, 0, second.stderr)
        claude_agent = self.path / "home/.claude/agents/scout.md"
        self.assertTrue(claude_agent.is_symlink())
        self.assertEqual((self.path / "home/.claude/CLAUDE.md").resolve(), self.project / "content/instructions/AGENTS.md")
        state = json.loads((self.path / "xdg/state/harness-kit/state.json").read_text())
        self.assertIn(str(claude_agent.parent.resolve() / claude_agent.name), state["links"])

    def test_scoped_install_deploys_only_requested_common_locations(self) -> None:
        claude = invoke(self.sandbox, "install", "--harness", "claude")
        self.assertEqual(claude.returncode, 0, claude.stderr)
        home = self.path / "home"
        self.assertTrue((home / ".claude/CLAUDE.md").is_symlink())
        self.assertFalse((home / ".agents/AGENTS.md").exists())
        self.assertFalse((home / ".pi/agent/AGENTS.md").exists())
        with temporary_sandbox() as sandbox:
            pi = invoke(sandbox, "install", "--harness", "pi")
            self.assertEqual(pi.returncode, 0, pi.stderr)
            self.assertFalse((sandbox.root / "home/.claude/CLAUDE.md").exists())
            self.assertTrue((sandbox.root / "home/.agents/AGENTS.md").is_symlink())
            self.assertTrue((sandbox.root / "home/.pi/agent/AGENTS.md").is_symlink())

    def test_install_does_not_claim_matching_unmanaged_instruction_link(self) -> None:
        destination = self.path / "home/.agents/AGENTS.md"
        destination.parent.mkdir(parents=True)
        destination.symlink_to(self.project / "content/instructions/AGENTS.md")
        result = invoke(self.sandbox, "install", "--harness", "pi")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(destination.resolve(), self.project / "content/instructions/AGENTS.md")
        state = json.loads((self.path / "xdg/state/harness-kit/state.json").read_text())
        self.assertNotIn(str(destination.parent.resolve() / destination.name), state["links"])

    def test_install_refuses_foreign_common_instruction_destinations(self) -> None:
        for harness, relative_destination in (("claude", ".claude/CLAUDE.md"), ("pi", ".agents/AGENTS.md"), ("pi", ".pi/agent/AGENTS.md")):
            with self.subTest(destination=relative_destination), temporary_sandbox() as sandbox:
                foreign = sandbox.root / "home" / relative_destination
                foreign.parent.mkdir(parents=True)
                foreign.write_text("foreign\n")
                result = invoke(sandbox, "install", "--harness", harness)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(foreign.read_text(), "foreign\n")
                self.assertFalse((sandbox.root / "commands").exists())

    def test_install_skip_unblocks_other_destinations(self) -> None:
        destination = self.path / "home/.claude/CLAUDE.md"
        destination.parent.mkdir(parents=True)
        foreign = self.path / "dotfiles/CLAUDE.md"
        foreign.parent.mkdir(parents=True)
        foreign.write_text("foreign\n")
        destination.symlink_to(foreign)
        result = invoke(self.sandbox, "install", "--harness", "claude", "--skip", str(destination))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("[SKIP]", result.stdout)
        self.assertEqual(destination.resolve(), foreign.resolve())
        self.assertTrue((self.path / "home/.claude/agents/scout.md").is_symlink())
        state = json.loads((self.path / "xdg/state/harness-kit/state.json").read_text())
        self.assertNotIn(str(destination.resolve()), state["links"])

    def test_install_adopts_known_legacy_pi_instruction_link(self) -> None:
        destination = self.path / "home/.pi/agent/AGENTS.md"
        destination.parent.mkdir(parents=True)
        legacy = self.path / "home/dev/pi-kit/config/pi/AGENTS.md"
        legacy.parent.mkdir(parents=True)
        legacy.write_text("legacy\n")
        destination.symlink_to(legacy)
        result = invoke(self.sandbox, "install", "--harness", "pi", "--adopt-legacy")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(destination.resolve(), self.project / "content/instructions/AGENTS.md")

    def test_unselected_malformed_content_is_not_loaded(self) -> None:
        metadata = self.project / "content/agents/scout/agent.toml"
        original = metadata.read_text()
        metadata.write_text(original.replace("[claude]", "pi = \"broken\"\n\n[claude]").replace("\n[pi]\nisolated = true\nprovider = \"codex\"\n", "\n"))
        try:
            self.assertEqual(invoke(self.sandbox, "preview", "--component", "skills").returncode, 0)
            self.assertEqual(invoke(self.sandbox, "preview", "--harness", "claude", "--component", "agents").returncode, 0)
            self.assertEqual(invoke(self.sandbox, "preview", "--harness", "pi", "--component", "agents").returncode, 2)
        finally:
            metadata.write_text(original)

    def test_agents_only_does_not_require_instructions(self) -> None:
        instructions = self.project / "content/instructions/AGENTS.md"
        original = instructions.read_text()
        instructions.unlink()
        try:
            result = invoke(self.sandbox, "preview", "--harness", "claude", "--component", "agents")
            self.assertEqual(result.returncode, 0, result.stderr)
        finally:
            instructions.write_text(original)

    def test_generated_drift_is_scoped_to_selected_harness(self) -> None:
        self.assertEqual(invoke(self.sandbox, "install").returncode, 0)
        pi_agent = self.project / ".generated/pi/agents/scout.md"
        original = pi_agent.read_text()
        pi_agent.write_text("drift\n")
        try:
            self.assertEqual(invoke(self.sandbox, "check", "--harness", "claude", "--component", "agents").returncode, 0)
            self.assertEqual(invoke(self.sandbox, "check", "--harness", "pi", "--component", "agents").returncode, 1)
        finally:
            pi_agent.write_text(original)

    def test_pi_rendering_does_not_replace_claude_generated_agents(self) -> None:
        self.assertEqual(invoke(self.sandbox, "install", "--harness", "claude", "--component", "agents").returncode, 0)
        claude_agent = self.project / ".generated/claude/agents/scout.md"
        original = claude_agent.read_text()
        pi = invoke(self.sandbox, "install", "--harness", "pi", "--component", "agents")
        self.assertEqual(pi.returncode, 0, pi.stderr)
        self.assertEqual(claude_agent.read_text(), original)

    def test_pi_agents_preview_lists_render_and_registration_work(self) -> None:
        result = invoke(self.sandbox, "preview", "--harness", "pi", "--component", "agents")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("[RENDER]", result.stdout)
        self.assertIn(str(self.project / ".generated/pi/agents"), result.stdout)
        self.assertIn("[NPM CI]", result.stdout)
        self.assertIn("[PI INSTALL]", result.stdout)
        self.assertIn(str(self.project), result.stdout)
        self.assertNotIn(str(SOURCE_ROOT), result.stdout)

    def test_agent_install_creates_missing_generated_parent(self) -> None:
        generated = self.project / ".generated"
        self.assertFalse(generated.exists())
        result = invoke(self.sandbox, "install", "--harness", "claude", "--component", "agents")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((generated / "claude/agents/scout.md").is_file())

    def test_selected_generated_tree_detects_and_cleans_stale_files(self) -> None:
        self.assertEqual(invoke(self.sandbox, "install").returncode, 0)
        stale = self.project / ".generated/claude/agents/stale/ghost.md"
        legacy = self.project / ".generated/claude/legacy.md"
        stale.parent.mkdir(parents=True)
        stale.write_text("stale\n")
        legacy.write_text("legacy\n")
        self.assertEqual(invoke(self.sandbox, "check", "--harness", "claude", "--component", "agents").returncode, 1)
        reinstall = invoke(self.sandbox, "install", "--harness", "claude", "--component", "agents")
        self.assertEqual(reinstall.returncode, 0, reinstall.stderr)
        self.assertFalse(stale.exists())
        self.assertFalse(legacy.exists())

    def test_pi_agents_plan_reports_legacy_package_migration(self) -> None:
        home = self.path / "home"
        settings = home / ".pi/agent/settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(json.dumps({"packages": [str(home / "dev/pi-kit")]}) + "\n")
        blocked = invoke(self.sandbox, "preview", "--harness", "pi", "--component", "agents")
        self.assertEqual(blocked.returncode, 2)
        self.assertIn("[CONFLICT]", blocked.stdout)
        self.assertIn("legacy pi-kit package is registered", blocked.stdout)
        adopted = invoke(self.sandbox, "install", "--harness", "pi", "--component", "agents", "--dry-run", "--adopt-legacy")
        self.assertEqual(adopted.returncode, 0, adopted.stderr)
        self.assertIn("[PI REMOVE]", adopted.stdout)
        self.assertIn(str(home / "dev/pi-kit"), adopted.stdout)
        self.assertFalse((self.path / "commands").exists())


if __name__ == "__main__":
    unittest.main()
