from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
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


_MUTATION_ENVIRONMENT_PATHS = frozenset((
    "HOME", "CODEX_HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME",
    "TMPDIR", "NPM_CONFIG_USERCONFIG", "NPM_CONFIG_CACHE", "NPM_CONFIG_PREFIX", "PI_HOME",
    "GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM", "HARNESS_LOG", "PATH", "PYTHONPATH",
))


def subprocess_environment(sandbox: Sandbox, environment_override: dict[str, str | None] | None) -> dict[str, str]:
    sandbox.assert_contained()
    fake_bin = sandbox.root / "bin"
    fake_bin.mkdir(exist_ok=True)
    for name in ("npm", "pi"):
        command = fake_bin / name
        command.write_text("#!/bin/sh\nprintf '%s|%s %s\\n' \"$PWD\" \"$0\" \"$*\" >> \"$HARNESS_LOG\"\n[ -z \"${HARNESS_SHIM_HOOK:-}\" ] || \"$HARNESS_SHIM_HOOK\" \"$0\"\n")
        command.chmod(0o755)
    environment = {
        "HOME": str(sandbox.root / "home"), "CODEX_HOME": str(sandbox.root / "home/codex-home"),
        "XDG_CONFIG_HOME": str(sandbox.root / "xdg/config"),
        "XDG_CACHE_HOME": str(sandbox.root / "xdg/cache"), "XDG_DATA_HOME": str(sandbox.root / "xdg/data"),
        "TMPDIR": str(sandbox.root / "tmp"), "NPM_CONFIG_USERCONFIG": str(sandbox.root / "npm/config/npmrc"),
        "NPM_CONFIG_CACHE": str(sandbox.root / "npm/cache"), "NPM_CONFIG_PREFIX": str(sandbox.root / "npm/prefix"),
        "PI_HOME": str(sandbox.root / "pi"), "GIT_CONFIG_GLOBAL": str(sandbox.root / "git/global"),
        "GIT_CONFIG_SYSTEM": str(sandbox.root / "git/system"), "GIT_CONFIG_NOSYSTEM": "1",
        "PATH": str(fake_bin), "PYTHONPATH": str(sandbox.project / "src"),
        "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1", "HARNESS_LOG": str(sandbox.root / "commands"),
    }
    hook = sandbox.root / "shim-hook"
    if hook.exists():
        environment["HARNESS_SHIM_HOOK"] = str(hook)
    for key, value in (environment_override or {}).items():
        if key in _MUTATION_ENVIRONMENT_PATHS:
            if value is None:
                if key == "CODEX_HOME":
                    environment.pop(key, None)
                    continue
                raise RuntimeError(f"mutating subprocess environment removes sandbox boundary: {key}")
            candidate = Path(value)
            if not candidate.is_absolute() or not candidate.resolve().is_relative_to(sandbox.root.resolve()):
                raise RuntimeError(f"mutating subprocess environment escapes sandbox: {key}={value!r}")
        if value is None:
            environment.pop(key, None)
        else:
            environment[key] = value
    return environment


def invoke(sandbox: Sandbox, *arguments: str, environment_override: dict[str, str | None] | None = None) -> subprocess.CompletedProcess[str]:
    # Mutating CLI subprocesses may only receive sandbox-contained path values.
    environment = subprocess_environment(sandbox, environment_override)
    cwd = sandbox.project.resolve()
    if not cwd.is_relative_to(sandbox.root.resolve()) or cwd == SOURCE_ROOT.resolve():
        raise RuntimeError("CLI subprocess must run from sandbox project")
    return subprocess.run([sys.executable, "-m", "harness_kit.cli", *arguments], cwd=cwd, env=environment, text=True, capture_output=True)


class HarnessKitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.sandbox = create_sandbox(Path(self.temp.name))
        self.path = self.sandbox.root
        self.project = self.sandbox.project

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_fresh_install_creates_links_without_state(self) -> None:
        result = invoke(self.sandbox, "install", "--harness", "claude", "--component", "instructions")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.path / "home/.claude/CLAUDE.md").is_symlink())
        self.assertFalse((self.path / "home/.local/state/harness-kit").exists())

    def test_malformed_historical_state_is_ignored_and_preserved(self) -> None:
        historical = self.path / "home/.local/state/harness-kit/state.json"
        historical.parent.mkdir(parents=True)
        original = "not json\n"
        historical.write_text(original)
        result = invoke(self.sandbox, "install", "--harness", "claude", "--component", "instructions")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(historical.read_text(), original)

    def test_historical_state_symlink_is_ignored_and_preserved(self) -> None:
        historical_root = self.path / "home/.local/state/harness-kit"
        historical_root.mkdir(parents=True)
        target = self.path / "historical-target"
        target.write_text("protected\n")
        historical = historical_root / "state.json"
        historical.symlink_to(target)
        result = invoke(self.sandbox, "install", "--harness", "claude", "--component", "instructions")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(historical.is_symlink())
        self.assertEqual(historical.resolve(), target)

    def test_symlinked_historical_state_ancestor_is_ignored_and_preserved(self) -> None:
        state_root = self.path / "home/.local/state"
        outside = self.path / "historical"
        outside.mkdir()
        state_root.parent.mkdir(parents=True)
        state_root.symlink_to(outside, target_is_directory=True)
        result = invoke(self.sandbox, "install", "--harness", "claude", "--component", "instructions")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(state_root.is_symlink())
        self.assertEqual(state_root.resolve(), outside)

    def test_preview_is_read_only(self) -> None:
        result = invoke(self.sandbox, "preview")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("[CREATE]", result.stdout)
        self.assertIn(str(self.project), result.stdout)
        self.assertFalse((self.path / "commands").exists())
        self.assertFalse((self.path / "home").exists())

    def test_install_dry_run_is_rejected(self) -> None:
        result = invoke(self.sandbox, "install", "--dry-run")
        self.assertEqual(result.returncode, 2)
        self.assertIn("unrecognized arguments: --dry-run", result.stderr)
        self.assertFalse((self.path / "commands").exists())
        self.assertFalse((self.path / "home").exists())

    def test_mutating_subprocess_rejects_unsafe_path_overrides(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "escapes sandbox"):
            invoke(self.sandbox, "install", environment_override={"HOME": "/"})
        with self.assertRaisesRegex(RuntimeError, "removes sandbox boundary"):
            invoke(self.sandbox, "install", environment_override={"PATH": None})

    def test_install_is_stateless_and_idempotent(self) -> None:
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

    def test_codex_skills_only_uses_shared_agents_destination(self) -> None:
        preview = invoke(self.sandbox, "preview", "--harness", "codex", "--component", "skills")
        self.assertEqual(preview.returncode, 0, preview.stderr)
        self.assertIn(".agents/skills/code-review", preview.stdout)
        self.assertNotIn("codex-home", preview.stdout)
        result = invoke(self.sandbox, "install", "--harness", "codex", "--component", "skills")
        self.assertEqual(result.returncode, 0, result.stderr)
        destination = self.path / "home/.agents/skills/code-review"
        self.assertTrue(destination.is_symlink())
        self.assertEqual(destination.resolve(), self.project / "content/skills/code-review")

    def test_all_plans_each_shared_skill_once(self) -> None:
        result = invoke(self.sandbox, "preview", "--harness", "all", "--component", "skills")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.count(".agents/skills/code-review"), 1)

    def test_codex_skills_only_does_not_render_agents_or_run_commands(self) -> None:
        result = invoke(self.sandbox, "install", "--harness", "codex", "--component", "skills")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.project / ".generated").exists())
        self.assertFalse((self.path / "commands").exists())
        self.assertFalse((self.path / "home/.claude").exists())
        self.assertFalse((self.path / "home/.pi").exists())

    def test_codex_shared_skill_matching_pi_link_is_noop(self) -> None:
        self.assertEqual(invoke(self.sandbox, "install", "--harness", "pi", "--component", "skills").returncode, 0)
        result = invoke(self.sandbox, "install", "--harness", "codex", "--component", "skills")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("[CREATE]", result.stdout)
        self.assertIn("[NOOP]", result.stdout)

    def test_pi_shared_skill_matching_codex_link_is_noop(self) -> None:
        self.assertEqual(invoke(self.sandbox, "install", "--harness", "codex", "--component", "skills").returncode, 0)
        result = invoke(self.sandbox, "install", "--harness", "pi", "--component", "skills")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("[CREATE]", result.stdout)
        self.assertIn("[NOOP]", result.stdout)

    def test_pi_and_codex_skill_installs_are_idempotent(self) -> None:
        first = invoke(self.sandbox, "install", "--harness", "codex", "--component", "skills")
        self.assertEqual(first.returncode, 0, first.stderr)
        second = invoke(self.sandbox, "install", "--harness", "pi", "--component", "skills")
        self.assertEqual(second.returncode, 0, second.stderr)
        check = invoke(self.sandbox, "check", "--harness", "codex", "--component", "skills")
        self.assertEqual(check.returncode, 0, check.stderr)

    def test_codex_shared_skill_parent_symlink_and_file_fail_closed(self) -> None:
        outside = self.path / "outside"
        outside.mkdir()
        parent = self.path / "home/.agents/skills"
        parent.parent.mkdir(parents=True)
        parent.symlink_to(outside, target_is_directory=True)
        result = invoke(self.sandbox, "preview", "--harness", "codex", "--component", "skills")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("symlinked ancestor", result.stderr)
        parent.unlink()
        parent.write_text("protected\n")
        result = invoke(self.sandbox, "preview", "--harness", "codex", "--component", "skills")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("non-directory ancestor", result.stderr)

    def test_codex_shared_skill_create_is_revalidated_before_linking(self) -> None:
        outside = self.path / "outside"
        outside.mkdir()
        canary = outside / "canary"
        canary.write_text("protected\n")
        parent = self.path / "home/.agents/skills"
        hook = self.path / "shim-hook"
        hook.write_text(
            "#!/bin/sh\n"
            "if [ \"$1\" = \"%s/bin/npm\" ]; then /bin/mkdir -p \"%s\"; /bin/rm -rf \"%s\"; /bin/ln -s \"%s\" \"%s\"; fi\n"
            % (self.path, parent.parent, parent, outside, parent)
        )
        hook.chmod(0o755)
        result = invoke(self.sandbox, "install", "--harness", "all", "--component", "agents", "--component", "skills")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("symlinked ancestor", result.stderr)
        self.assertEqual(canary.read_text(), "protected\n")
        self.assertFalse((outside / "code-review").exists())

    def test_codex_shared_skill_foreign_destinations_are_preserved(self) -> None:
        destination = self.path / "home/.agents/skills/code-review"
        destination.parent.mkdir(parents=True)
        foreign = self.path / "foreign"
        foreign.write_text("protected\n")
        destination.write_text("also protected\n")
        result = invoke(self.sandbox, "install", "--harness", "codex", "--component", "skills")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(destination.read_text(), "also protected\n")
        destination.unlink()
        destination.symlink_to(foreign)
        result = invoke(self.sandbox, "install", "--harness", "codex", "--component", "skills")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(destination.resolve(), foreign.resolve())

    def test_codex_skills_ignore_directories_without_skill_md(self) -> None:
        ignored = self.project / "content/skills/no-skill-md"
        ignored.mkdir()
        result = invoke(self.sandbox, "preview", "--harness", "codex", "--component", "skills")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("no-skill-md", result.stdout)

    def test_codex_component_scope_preserves_other_links(self) -> None:
        result = invoke(self.sandbox, "install", "--harness", "codex", "--component", "skills")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.path / "home/codex-home/agents").exists())
        self.assertFalse((self.project / ".generated").exists())

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

    def test_managed_parent_symlinks_fail_closed_for_every_family(self) -> None:
        families = (
            (".claude", "claude", "instructions"),
            (".claude/agents", "claude", "agents"),
            (".claude/skills", "claude", "skills"),
            (".agents", "pi", "instructions"),
            (".agents/skills", "pi", "skills"),
            (".pi", "pi", "instructions"),
            (".pi/agent", "pi", "instructions"),
            ("codex-home", "codex", "agents"),
        )
        for parent_relative, harness, component in families:
            with self.subTest(parent=parent_relative), temporary_sandbox() as sandbox:
                outside = sandbox.root / "outside"
                canary = outside / "canary"
                outside.mkdir()
                canary.write_text("protected\n")
                parent = sandbox.root / "home" / parent_relative
                parent.parent.mkdir(parents=True, exist_ok=True)
                parent.symlink_to(outside, target_is_directory=True)
                for command in ("preview", "install", "check"):
                    result = invoke(sandbox, command, "--harness", harness, "--component", component)
                    self.assertEqual(result.returncode, 2, (command, result.stderr))
                    self.assertIn("symlinked ancestor", result.stderr)
                    self.assertEqual(canary.read_text(), "protected\n")
                    self.assertFalse((sandbox.root / "commands").exists())

    def test_managed_parent_files_fail_closed_for_every_family(self) -> None:
        families = (".claude", ".claude/agents", ".claude/skills", ".agents", ".agents/skills", ".pi", ".pi/agent", "codex-home")
        for parent_relative in families:
            with self.subTest(parent=parent_relative), temporary_sandbox() as sandbox:
                parent = sandbox.root / "home" / parent_relative
                parent.parent.mkdir(parents=True, exist_ok=True)
                parent.write_text("not a directory\n")
                result = invoke(sandbox, "preview")
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("non-directory ancestor", result.stderr)
                self.assertFalse((sandbox.root / "commands").exists())

    def test_invalid_parent_blocks_pi_commands_before_install(self) -> None:
        outside = self.path / "outside"
        outside.mkdir()
        canary = outside / "canary"
        canary.write_text("protected\n")
        parent = self.path / "home/.agents"
        parent.parent.mkdir(parents=True)
        parent.symlink_to(outside, target_is_directory=True)
        result = invoke(self.sandbox, "install", "--harness", "pi")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(canary.read_text(), "protected\n")
        self.assertFalse((self.path / "commands").exists())

    def test_install_revalidates_parent_after_npm_race(self) -> None:
        outside = self.path / "outside"
        outside.mkdir()
        canary = outside / "canary"
        canary.write_text("protected\n")
        parent = self.path / "home/.agents"
        parent.parent.mkdir(parents=True)
        hook = self.path / "shim-hook"
        hook.write_text(
            "#!/bin/sh\n"
            "if [ \"$1\" = \"%s/bin/npm\" ]; then /bin/rm -rf \"%s\"; /bin/ln -s \"%s\" \"%s\"; fi\n"
            % (self.path, parent, outside, parent)
        )
        hook.chmod(0o755)
        result = invoke(self.sandbox, "install", "--harness", "pi")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("symlinked ancestor", result.stderr)
        self.assertEqual(canary.read_text(), "protected\n")
        self.assertFalse((outside / "AGENTS.md").exists())

    def test_install_revalidates_create_before_linking(self) -> None:
        foreign = self.path / "foreign"
        foreign.write_text("foreign\n")
        destination = self.path / "home/.agents/AGENTS.md"
        hook = self.path / "shim-hook"
        hook.write_text(
            "#!/bin/sh\n"
            "if [ \"$1\" = \"%s/bin/npm\" ]; then /bin/mkdir -p \"%s\"; /bin/ln -s \"%s\" \"%s\"; fi\n"
            % (self.path, destination.parent, foreign, destination)
        )
        hook.chmod(0o755)
        result = invoke(self.sandbox, "install", "--harness", "pi")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("substituted destination", result.stderr)
        self.assertTrue(destination.is_symlink())
        self.assertEqual(destination.resolve(), foreign)
        self.assertEqual(foreign.read_text(), "foreign\n")

    def test_install_conflicts_when_existing_link_target_differs(self) -> None:
        destination = self.path / "home/.agents/AGENTS.md"
        target_a = self.path / "target-a"
        target_b = self.project / "content/instructions/AGENTS.md"
        target_a.write_text("target A\n")
        destination.parent.mkdir(parents=True)
        destination.symlink_to(target_a)
        original_a = target_a.read_text()

        preview = invoke(self.sandbox, "preview")
        self.assertEqual(preview.returncode, 2, preview.stderr)
        self.assertIn("[CONFLICT]", preview.stdout)
        self.assertNotIn("[UPDATE]", preview.stdout)

        result = invoke(self.sandbox, "install")

        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("[CONFLICT]", result.stdout)
        self.assertNotIn("[UPDATE]", result.stdout)
        self.assertFalse((self.path / "commands").exists())
        self.assertTrue(destination.is_symlink())
        self.assertEqual(destination.resolve(), target_a.resolve())
        self.assertEqual(target_a.read_text(), original_a)
        self.assertNotEqual(destination.resolve(), target_b.resolve())

    def test_stale_deployed_skill_link_is_preserved_when_source_leaves_catalog(self) -> None:
        # A stale deployed link is intentionally different from stale generated
        # files, which install must still detect and clean (see its dedicated test).
        self.assertEqual(invoke(self.sandbox, "install", "--harness", "pi", "--component", "skills").returncode, 0)
        destination = self.path / "home/.agents/skills/dod"
        old_target = destination.resolve()
        retired = self.path / "retired-skill"
        old_target.rename(retired)
        self.assertTrue(destination.is_symlink())
        self.assertFalse(destination.exists())

        preview = invoke(self.sandbox, "preview", "--harness", "pi", "--component", "skills")
        self.assertEqual(preview.returncode, 0, preview.stderr)
        self.assertNotIn("[REMOVE]", preview.stdout)

        installed = invoke(self.sandbox, "install", "--harness", "pi", "--component", "skills")
        self.assertEqual(installed.returncode, 0, installed.stderr)
        self.assertTrue(destination.is_symlink())
        self.assertEqual(os.readlink(destination), str(old_target))

        checked = invoke(self.sandbox, "check", "--harness", "pi", "--component", "skills")
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertTrue(destination.is_symlink())
        self.assertEqual(os.readlink(destination), str(old_target))


    def test_component_scoped_install_preserves_unselected_links(self) -> None:
        self.assertEqual(invoke(self.sandbox, "install").returncode, 0)
        second = invoke(self.sandbox, "install", "--component", "skills")
        self.assertEqual(second.returncode, 0, second.stderr)
        agent = self.path / "home/.claude/agents/scout.md"
        self.assertTrue(agent.is_symlink())
        self.assertTrue((self.path / "home/.claude/CLAUDE.md").is_symlink())

    def test_codex_agents_render_required_toml_fields(self) -> None:
        result = invoke(self.sandbox, "install", "--harness", "codex", "--component", "agents")
        self.assertEqual(result.returncode, 0, result.stderr)
        generated = self.project / ".generated/codex/agents/scout.toml"
        data = tomllib.loads(generated.read_text())
        self.assertEqual(set(data), {"name", "description", "model", "model_reasoning_effort", "developer_instructions"})
        self.assertEqual(data["name"], "scout")
        self.assertEqual(data["model"], "gpt-5.6-terra")
        self.assertEqual(data["model_reasoning_effort"], "medium")
        self.assertEqual(data["developer_instructions"], (self.project / "content/agents/scout/prompt.md").read_text())
        self.assertTrue((self.path / "home/codex-home/agents/scout.toml").is_symlink())
        self.assertFalse((self.path / "commands").exists())

    def test_codex_render_round_trips_authored_special_characters(self) -> None:
        prompt = 'quotes " and /slashes/ and \\slashes\\\nmultiline\ntriple """ unicode λ DEL \x7f low \x00\x01\x0b\t'
        prompt_path = self.project / "content/agents/scout/prompt.md"
        prompt_path.write_text(prompt)
        result = invoke(self.sandbox, "install", "--harness", "codex", "--component", "agents")
        self.assertEqual(result.returncode, 0, result.stderr)
        rendered = tomllib.loads((self.project / ".generated/codex/agents/scout.toml").read_text())
        self.assertEqual(rendered["developer_instructions"], prompt)

    def test_codex_matching_agent_check_is_noop_and_preserves_link(self) -> None:
        self.assertEqual(invoke(self.sandbox, "install", "--harness", "codex", "--component", "agents").returncode, 0)
        destination = self.path / "home/codex-home/agents/scout.toml"
        original = destination.readlink()
        result = invoke(self.sandbox, "check", "--harness", "codex", "--component", "agents")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(destination.readlink(), original)
        self.assertNotIn("[CREATE]", result.stdout)

    def test_codex_generated_ancestor_symlink_fails_without_external_mutation(self) -> None:
        outside = self.path / "outside-generated"
        outside.mkdir()
        sentinel = outside / "sentinel"
        sentinel.write_text("protected\n")
        (self.project / ".generated").symlink_to(outside, target_is_directory=True)
        result = invoke(self.sandbox, "install", "--harness", "codex", "--component", "agents")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(sentinel.read_text(), "protected\n")
        self.assertEqual(sorted(path.name for path in outside.iterdir()), ["sentinel"])

    def test_all_agents_explicitly_renders_codex_and_runs_pi_bootstrap_once(self) -> None:
        result = invoke(self.sandbox, "install", "--harness", "all", "--component", "agents")
        self.assertEqual(result.returncode, 0, result.stderr)
        commands = (self.path / "commands").read_text().splitlines()
        self.assertEqual(len(commands), 2)
        self.assertEqual(sum("/npm " in line for line in commands), 1)
        self.assertEqual(sum("/pi " in line for line in commands), 1)
        self.assertTrue((self.project / ".generated/codex/agents/scout.toml").is_file())
        self.assertTrue((self.path / "home/codex-home/agents/scout.toml").is_symlink())

    def test_codex_check_routes_convergence_and_repairs_generated_drift(self) -> None:
        install = invoke(self.sandbox, "install", "--harness", "codex", "--component", "agents")
        self.assertEqual(install.returncode, 0, install.stderr)
        check = invoke(self.sandbox, "check", "--harness", "codex", "--component", "agents")
        self.assertEqual(check.returncode, 0, check.stderr)
        generated = self.project / ".generated/codex/agents/scout.toml"
        generated.write_text("broken = true\n")
        drift = invoke(self.sandbox, "check", "--harness", "codex", "--component", "agents")
        self.assertEqual(drift.returncode, 1)
        repaired = invoke(self.sandbox, "install", "--harness", "codex", "--component", "agents")
        self.assertEqual(repaired.returncode, 0, repaired.stderr)
        generated.unlink()
        missing = invoke(self.sandbox, "check", "--harness", "codex", "--component", "agents")
        self.assertEqual(missing.returncode, 1)
        stale = self.project / ".generated/codex/agents/stale.toml"
        stale.write_text("stale = true\n")
        stale_check = invoke(self.sandbox, "check", "--harness", "codex", "--component", "agents")
        self.assertEqual(stale_check.returncode, 1)
        repaired = invoke(self.sandbox, "install", "--harness", "codex", "--component", "agents")
        self.assertEqual(repaired.returncode, 0, repaired.stderr)
        self.assertFalse(stale.exists())

    def test_codex_install_conflicts_preserve_regular_and_mismatched_destinations(self) -> None:
        destination = self.path / "home/codex-home/agents/scout.toml"
        destination.parent.mkdir(parents=True)
        regular = "foreign\n"
        destination.write_text(regular)
        result = invoke(self.sandbox, "install", "--harness", "codex", "--component", "agents")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(destination.read_text(), regular)
        destination.unlink()
        foreign = self.path / "foreign.toml"
        foreign.write_text("foreign\n")
        destination.symlink_to(foreign)
        result = invoke(self.sandbox, "install", "--harness", "codex", "--component", "agents")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(destination.resolve(), foreign.resolve())
        destination.unlink()
        matching = invoke(self.sandbox, "install", "--harness", "codex", "--component", "agents")
        self.assertEqual(matching.returncode, 0, matching.stderr)
        self.assertTrue(destination.is_symlink())

    def test_codex_render_preserves_other_generated_harnesses(self) -> None:
        self.assertEqual(invoke(self.sandbox, "install", "--harness", "claude", "--component", "agents").returncode, 0)
        claude = self.project / ".generated/claude/agents/scout.md"
        original = claude.read_text()
        result = invoke(self.sandbox, "install", "--harness", "codex", "--component", "agents")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(claude.read_text(), original)

    def test_codex_then_other_harness_preserves_generated_tree(self) -> None:
        first = invoke(self.sandbox, "install", "--harness", "codex", "--component", "agents")
        self.assertEqual(first.returncode, 0, first.stderr)
        codex = self.project / ".generated/codex/agents/scout.toml"
        original = codex.read_text()
        second = invoke(self.sandbox, "install", "--harness", "pi", "--component", "agents")
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(codex.read_text(), original)

    def test_codex_preview_is_read_only_and_lists_codex_operations(self) -> None:
        result = invoke(self.sandbox, "preview", "--harness", "codex", "--component", "agents")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("[RENDER]", result.stdout)
        self.assertIn("codex/agents", result.stdout)
        self.assertIn("[CREATE]", result.stdout)
        self.assertIn("codex-home/agents/scout.toml", result.stdout)
        self.assertFalse((self.project / ".generated").exists())
        self.assertFalse((self.path / "home/codex-home").exists())

    def test_codex_agents_default_home_and_safe_override(self) -> None:
        default = invoke(self.sandbox, "install", "--harness", "codex", "--component", "agents", environment_override={"CODEX_HOME": None})
        self.assertEqual(default.returncode, 0, default.stderr)
        self.assertTrue((self.path / "home/.codex/agents/scout.toml").is_symlink())
        override = self.path / "home/custom/codex"
        result = invoke(self.sandbox, "install", "--harness", "codex", "--component", "agents", environment_override={"CODEX_HOME": str(override)})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((override / "agents/scout.toml").is_symlink())

    def test_codex_agents_do_not_install_skills_or_instructions(self) -> None:
        result = invoke(self.sandbox, "install", "--harness", "codex", "--component", "agents")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.path / "home/.claude").exists())
        self.assertFalse((self.path / "home/.agents").exists())
        self.assertFalse((self.path / "home/.pi").exists())

    def test_codex_agents_reject_unsafe_codex_home(self) -> None:
        target = self.path / "home/codex-target"
        target.mkdir(parents=True)
        link = self.path / "home/codex-link"
        link.symlink_to(target, target_is_directory=True)
        result = invoke(self.sandbox, "preview", "--harness", "codex", "--component", "agents", environment_override={"CODEX_HOME": str(link)})
        self.assertEqual(result.returncode, 2)
        self.assertIn("symlinked ancestor", result.stderr)
        self.assertFalse((self.path / "commands").exists())

    def test_codex_generated_file_ancestors_fail_closed_without_mutation(self) -> None:
        for relative in (".generated", ".generated/codex"):
            with self.subTest(relative=relative):
                ancestor = self.project / relative
                ancestor.parent.mkdir(parents=True, exist_ok=True)
                ancestor.write_text("protected\n")
                result = invoke(self.sandbox, "check", "--harness", "codex", "--component", "agents")
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual(ancestor.read_text(), "protected\n")
                ancestor.unlink()

    def test_codex_install_revalidates_managed_root_race(self) -> None:
        outside = self.path / "outside-codex"
        outside.mkdir()
        canary = outside / "canary"
        canary.write_text("protected\n")
        managed = self.path / "home/codex-home"
        managed.mkdir(parents=True)
        hook = self.path / "shim-hook"
        hook.write_text(
            "#!/bin/sh\n"
            "if [ \"$1\" = \"%s/bin/npm\" ]; then /bin/rm -rf \"%s\"; /bin/ln -s \"%s\" \"%s\"; fi\n"
            % (self.path, managed, outside, managed)
        )
        hook.chmod(0o755)
        result = invoke(self.sandbox, "install", "--harness", "all", "--component", "agents")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("symlinked ancestor", result.stderr)
        self.assertEqual(canary.read_text(), "protected\n")
        self.assertFalse((outside / "agents").exists())

    def test_codex_agents_reject_symlinked_and_file_managed_ancestors(self) -> None:
        outside = self.path / "outside-codex"
        outside.mkdir()
        ancestor = self.path / "home/codex-ancestor"
        ancestor.parent.mkdir(parents=True)
        for replacement in ("symlink", "file"):
            with self.subTest(replacement=replacement):
                if ancestor.is_symlink() or ancestor.exists():
                    if ancestor.is_dir() and not ancestor.is_symlink():
                        shutil.rmtree(ancestor)
                    else:
                        ancestor.unlink()
                if replacement == "symlink":
                    ancestor.symlink_to(outside, target_is_directory=True)
                else:
                    ancestor.write_text("not a directory\n")
                result = invoke(self.sandbox, "preview", "--harness", "codex", "--component", "agents", environment_override={"CODEX_HOME": str(ancestor / "codex")})
                self.assertEqual(result.returncode, 2)

    def test_codex_agents_reject_raw_dot_components_before_mutation(self) -> None:
        for component in (".", ".."):
            with self.subTest(component=component):
                sentinel = self.path / "home/codex-sentinel"
                sentinel.parent.mkdir(parents=True, exist_ok=True)
                sentinel.write_text("protected\n")
                value = str(self.path / "home") + f"/{component}/codex-target"
                result = invoke(self.sandbox, "install", "--harness", "codex", "--component", "agents", environment_override={"CODEX_HOME": value})
                self.assertEqual(result.returncode, 2)
                self.assertEqual(sentinel.read_text(), "protected\n")
                self.assertFalse((self.project / ".generated").exists())

    def test_unsafe_agent_name_fails_before_mutation(self) -> None:
        canary = self.project.parent / "outside-canary"
        canary.write_text("protected\\n")
        metadata = self.project / "content/agents/scout/agent.toml"
        metadata.write_text(metadata.read_text().replace('name = "scout"', 'name = "../../outside-canary"'))
        result = invoke(self.sandbox, "install", "--harness", "claude", "--component", "agents")
        self.assertEqual(result.returncode, 2)
        self.assertIn("safe identifier", result.stderr)
        self.assertEqual(canary.read_text(), "protected\\n")
        self.assertFalse((self.project / ".generated").exists())

    def test_shared_reasoning_effort_renders_for_all_harnesses(self) -> None:
        result = invoke(self.sandbox, "install", "--harness", "all", "--component", "agents")
        self.assertEqual(result.returncode, 0, result.stderr)
        expected_models = {"builder": "gpt-5.6-terra", "debugger": "gpt-5.6-sol", "refuter": "gpt-5.6-sol", "researcher": "gpt-5.6-terra", "scout": "gpt-5.6-terra"}
        for name, model in expected_models.items():
            metadata = tomllib.loads((self.project / f"content/agents/{name}/agent.toml").read_text())
            self.assertEqual(metadata["reasoning_effort"], "medium")
            self.assertIn("effort: medium\n", (self.project / f".generated/claude/agents/{name}.md").read_text())
            self.assertIn("thinking: medium\n", (self.project / f".generated/pi/agents/{name}.md").read_text())
            codex = tomllib.loads((self.project / f".generated/codex/agents/{name}.toml").read_text())
            self.assertEqual(codex["model"], model)
            self.assertEqual(codex["model_reasoning_effort"], "medium")

    def test_harness_overrides_take_precedence(self) -> None:
        metadata = self.project / "content/agents/scout/agent.toml"
        metadata.write_text(
            metadata.read_text()
            .replace('[claude]\ncolor = "cyan"', '[claude]\ncolor = "cyan"\neffort = "low"')
            .replace('provider = "codex"', 'provider = "codex"\nthinking = "high"')
            + '\n[codex]\nmodel = "gpt-5.6-custom"\nmodel_reasoning_effort = "minimal"\n'
        )
        result = invoke(self.sandbox, "install", "--harness", "all", "--component", "agents")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("effort: low\n", (self.project / ".generated/claude/agents/scout.md").read_text())
        self.assertIn("thinking: high\n", (self.project / ".generated/pi/agents/scout.md").read_text())
        codex = tomllib.loads((self.project / ".generated/codex/agents/scout.toml").read_text())
        self.assertEqual(codex["model"], "gpt-5.6-custom")
        self.assertEqual(codex["model_reasoning_effort"], "minimal")

    def test_codex_policy_and_metadata_validation(self) -> None:
        policy = self.project / "policy.toml"
        original_policy = policy.read_text()
        policy.write_text(original_policy.replace('standard = "gpt-5.6-terra"', 'standard = 42', 1))
        result = invoke(self.sandbox, "preview", "--harness", "codex", "--component", "agents")
        self.assertEqual(result.returncode, 2)
        self.assertIn("invalid Codex model", result.stderr)
        policy.write_text(original_policy)

        metadata = self.project / "content/agents/scout/agent.toml"
        metadata.write_text(metadata.read_text() + "\n[codex]\nmodel_reasoning_effort = 1\n")
        result = invoke(self.sandbox, "preview", "--harness", "codex", "--component", "agents")
        self.assertEqual(result.returncode, 2)
        self.assertIn("model_reasoning_effort must be a non-empty string", result.stderr)

    def test_codex_model_override_must_be_a_non_empty_string(self) -> None:
        metadata = self.project / "content/agents/scout/agent.toml"
        original = metadata.read_text()
        for value in ("42", '\"\"'):
            with self.subTest(value=value):
                metadata.write_text(original + f"\n[codex]\nmodel = {value}\n")
                result = invoke(self.sandbox, "preview", "--harness", "codex", "--component", "agents")
                self.assertEqual(result.returncode, 2)
                self.assertIn("Codex model must be a non-empty string", result.stderr)

    def test_scoped_install_preserves_other_harness_links(self) -> None:
        self.assertEqual(invoke(self.sandbox, "install").returncode, 0)
        second = invoke(self.sandbox, "install", "--harness", "pi")
        self.assertEqual(second.returncode, 0, second.stderr)
        claude_agent = self.path / "home/.claude/agents/scout.md"
        self.assertTrue(claude_agent.is_symlink())
        self.assertEqual((self.path / "home/.claude/CLAUDE.md").resolve(), self.project / "content/instructions/AGENTS.md")

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

    def test_matching_link_is_stateless_noop(self) -> None:
        destination = self.path / "home/.agents/AGENTS.md"
        destination.parent.mkdir(parents=True)
        destination.symlink_to(self.project / "content/instructions/AGENTS.md")
        result = invoke(self.sandbox, "install", "--harness", "pi")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(destination.resolve(), self.project / "content/instructions/AGENTS.md")

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

    def test_install_foreign_destination_conflicts_and_blocks_other_destinations(self) -> None:
        destination = self.path / "home/.claude/CLAUDE.md"
        destination.parent.mkdir(parents=True)
        foreign = self.path / "dotfiles/CLAUDE.md"
        foreign.parent.mkdir(parents=True)
        foreign.write_text("foreign\n")
        destination.symlink_to(foreign)
        result = invoke(self.sandbox, "install", "--harness", "claude")
        self.assertEqual(result.returncode, 2)
        self.assertIn("[CONFLICT]", result.stdout)
        self.assertEqual(destination.resolve(), foreign.resolve())
        self.assertFalse((self.path / "home/.claude/agents/scout.md").exists())
        self.assertFalse((self.project / ".generated").exists())

    def test_legacy_pi_instruction_link_conflicts_and_is_preserved(self) -> None:
        destination = self.path / "home/.pi/agent/AGENTS.md"
        destination.parent.mkdir(parents=True)
        legacy = self.path / "home/dev/pi-kit/config/pi/AGENTS.md"
        legacy.parent.mkdir(parents=True)
        legacy.write_text("legacy\n")
        destination.symlink_to(legacy)
        preview = invoke(self.sandbox, "preview", "--harness", "pi")
        self.assertEqual(preview.returncode, 2)
        self.assertIn("[CONFLICT]", preview.stdout)
        result = invoke(self.sandbox, "install", "--harness", "pi")
        self.assertEqual(result.returncode, 2)
        self.assertIn("[CONFLICT]", result.stdout)
        self.assertEqual(os.readlink(destination), str(legacy))
        self.assertEqual(legacy.read_text(), "legacy\n")
        self.assertFalse((self.path / "commands").exists())
        self.assertFalse((self.project / ".generated").exists())

    def test_legacy_skill_link_conflicts_and_is_preserved(self) -> None:
        destination = self.path / "home/.agents/skills/code-review"
        destination.parent.mkdir(parents=True)
        legacy = self.path / "home/dev/skills/skills/code-review"
        legacy.mkdir(parents=True)
        target_file = legacy / "SKILL.md"
        target_file.write_text("legacy skill\n")
        destination.symlink_to(legacy)
        preview = invoke(self.sandbox, "preview", "--harness", "pi", "--component", "skills")
        self.assertEqual(preview.returncode, 2)
        self.assertIn("[CONFLICT]", preview.stdout)
        result = invoke(self.sandbox, "install", "--harness", "pi", "--component", "skills")
        self.assertEqual(result.returncode, 2)
        self.assertIn("[CONFLICT]", result.stdout)
        self.assertEqual(os.readlink(destination), str(legacy))
        self.assertEqual(target_file.read_text(), "legacy skill\n")

    def test_install_rejects_adopt_legacy_argument(self) -> None:
        result = invoke(self.sandbox, "install", "--adopt-legacy")
        self.assertEqual(result.returncode, 2)
        self.assertIn("unrecognized arguments: --adopt-legacy", result.stderr)

    def test_install_rejects_skip_argument(self) -> None:
        result = invoke(self.sandbox, "install", "--skip", "/tmp/destination")
        self.assertEqual(result.returncode, 2)
        self.assertIn("unrecognized arguments: --skip", result.stderr)

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

    def test_agents_render_plan_matches_selected_harnesses_for_preview(self) -> None:
        cases = (
            ("all", ("claude", "pi"), True),
            ("claude", ("claude",), False),
            ("pi", ("pi",), True),
        )
        for harness, rendered, includes_pi_work in cases:
            with self.subTest(harness=harness):
                result = invoke(self.sandbox, "preview", "--harness", harness, "--component", "agents")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.count("[RENDER]"), 1)
                for selected in rendered:
                    self.assertIn(str(self.project / f".generated/{selected}/agents"), result.stdout)
                for unselected in {"claude", "pi"} - set(rendered):
                    self.assertNotIn(str(self.project / f".generated/{unselected}/agents"), result.stdout)
                self.assertEqual("[NPM CI]" in result.stdout, includes_pi_work)
                self.assertEqual("[PI INSTALL]" in result.stdout, includes_pi_work)
                self.assertIn(str(self.project), result.stdout)
                self.assertNotIn(str(SOURCE_ROOT), result.stdout)
                self.assertFalse((self.path / "commands").exists())

    def test_install_plan_drives_preview_and_execution_in_order(self) -> None:
        generated = self.project / ".generated/pi/agents/scout.md"
        destination = self.path / "home/.claude/agents/scout.md"
        hook = self.path / "shim-hook"
        hook.write_text(
            "#!/bin/sh\n"
            f'test -f "{generated}" || exit 20\n'
            f'test ! -e "{destination}" || exit 21\n'
        )
        hook.chmod(0o755)

        preview = invoke(self.sandbox, "preview", "--component", "agents")
        self.assertEqual(preview.returncode, 0, preview.stderr)
        markers = ("[RENDER]", "[NPM CI]", "[PI INSTALL]", "[CREATE]")
        positions = [preview.stdout.index(marker) for marker in markers]
        self.assertEqual(positions, sorted(positions))

        installed = invoke(self.sandbox, "install", "--component", "agents")
        self.assertEqual(installed.returncode, 0, installed.stderr)
        self.assertEqual(installed.stdout, preview.stdout)
        self.assertTrue(generated.is_file())
        self.assertTrue(destination.is_symlink())
        commands = (self.path / "commands").read_text().splitlines()
        self.assertEqual(len(commands), 2)
        self.assertIn("npm ci", commands[0])
        self.assertIn("pi install", commands[1])

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

    def test_pi_agents_preview_ignores_string_form_old_package(self) -> None:
        home = self.path / "home"
        settings = home / ".pi/agent/settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(json.dumps({"packages": [str(home / "dev/pi-kit")]}) + "\n")
        result = invoke(self.sandbox, "preview", "--harness", "pi", "--component", "agents")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("[CONFLICT]", result.stdout)
        self.assertNotIn("[PI REMOVE]", result.stdout)

        installed = invoke(self.sandbox, "install", "--harness", "pi", "--component", "agents")
        self.assertEqual(installed.returncode, 0, installed.stderr)
        commands = (self.path / "commands").read_text()
        self.assertIn("npm ci", commands)
        self.assertIn("pi install", commands)
        self.assertNotIn("pi remove", commands)

    def test_pi_agents_preview_ignores_object_form_old_package(self) -> None:
        home = self.path / "home"
        settings = home / ".pi/agent/settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(json.dumps({"packages": [{"source": str(home / "dev/pi-kit")}]}) + "\n")
        result = invoke(self.sandbox, "preview", "--harness", "pi", "--component", "agents")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("[CONFLICT]", result.stdout)
        self.assertNotIn("[PI REMOVE]", result.stdout)

        installed = invoke(self.sandbox, "install", "--harness", "pi", "--component", "agents")
        self.assertEqual(installed.returncode, 0, installed.stderr)
        commands = (self.path / "commands").read_text()
        self.assertIn("npm ci", commands)
        self.assertIn("pi install", commands)
        self.assertNotIn("pi remove", commands)


if __name__ == "__main__":
    unittest.main()
