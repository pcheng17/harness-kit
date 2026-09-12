from __future__ import annotations

import json
import os
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


_MUTATION_ENVIRONMENT_PATHS = frozenset((
    "HOME", "CODEX_HOME", "XDG_STATE_HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME",
    "TMPDIR", "NPM_CONFIG_USERCONFIG", "NPM_CONFIG_CACHE", "NPM_CONFIG_PREFIX", "PI_HOME",
    "GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM", "HARNESS_LOG", "PATH", "PYTHONPATH",
))


def subprocess_environment(sandbox: Sandbox, environment_override: dict[str, str | None] | None, allow_unsafe_validation: bool = False) -> dict[str, str]:
    sandbox.assert_contained()
    fake_bin = sandbox.root / "bin"
    fake_bin.mkdir(exist_ok=True)
    for name in ("npm", "pi"):
        command = fake_bin / name
        command.write_text("#!/bin/sh\nprintf '%s|%s %s\\n' \"$PWD\" \"$0\" \"$*\" >> \"$HARNESS_LOG\"\n[ -z \"${HARNESS_SHIM_HOOK:-}\" ] || \"$HARNESS_SHIM_HOOK\" \"$0\"\n")
        command.chmod(0o755)
    environment = {
        "HOME": str(sandbox.root / "home"), "CODEX_HOME": str(sandbox.root / "codex-home"),
        "XDG_STATE_HOME": str(sandbox.root / "xdg/state"), "XDG_CONFIG_HOME": str(sandbox.root / "xdg/config"),
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
        if key in _MUTATION_ENVIRONMENT_PATHS and not allow_unsafe_validation:
            if value is None:
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


def invoke_validation(sandbox: Sandbox, environment_override: dict[str, str | None] | None = None) -> subprocess.CompletedProcess[str]:
    """Run state-root validation only; it never invokes the mutating CLI."""
    environment = subprocess_environment(sandbox, environment_override, allow_unsafe_validation=True)
    return subprocess.run(
        [sys.executable, "-c", "from harness_kit.cli import state_path; print(state_path())"],
        cwd=sandbox.project,
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

    def test_invalid_state_roots_fail_in_non_mutating_validation_subprocess(self) -> None:
        invalid_roots = ("", "relative/state", "/")
        for root in invalid_roots:
            with self.subTest(root=repr(root)), temporary_sandbox() as sandbox:
                result = invoke_validation(sandbox, {"XDG_STATE_HOME": root})
                self.assertNotEqual(result.returncode, 0, result.stderr)
                self.assertIn("XDG_STATE_HOME", result.stderr)
                self.assertFalse((sandbox.root / "commands").exists())

        with temporary_sandbox() as sandbox:
            result = invoke_validation(sandbox, {"XDG_STATE_HOME": None, "HOME": "/"})
            self.assertNotEqual(result.returncode, 0, result.stderr)
            self.assertIn("HOME", result.stderr)
            self.assertFalse((sandbox.root / "commands").exists())

    def test_mutating_subprocess_rejects_unsafe_path_overrides(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "escapes sandbox"):
            invoke(self.sandbox, "install", environment_override={"XDG_STATE_HOME": "/"})
        with self.assertRaisesRegex(RuntimeError, "removes sandbox boundary"):
            invoke(self.sandbox, "install", environment_override={"PATH": None})

    def test_state_ancestors_and_state_file_fail_closed_before_external_commands(self) -> None:
        cases = ("root-link", "root-file", "kit-link", "kit-file", "state-link", "state-file")
        for case in cases:
            with self.subTest(case=case), temporary_sandbox() as sandbox:
                root = sandbox.root / "xdg/state"
                state_directory = root / "harness-kit"
                outside = sandbox.root / "outside"
                outside.mkdir()
                if case == "root-link":
                    root.parent.mkdir(parents=True)
                    root.symlink_to(outside, target_is_directory=True)
                elif case == "root-file":
                    root.parent.mkdir(parents=True)
                    root.write_text("not a directory\n")
                elif case == "kit-link":
                    root.mkdir(parents=True)
                    state_directory.symlink_to(outside, target_is_directory=True)
                elif case == "kit-file":
                    root.mkdir(parents=True)
                    state_directory.write_text("not a directory\n")
                else:
                    state_directory.mkdir(parents=True)
                    state = state_directory / "state.json"
                    if case == "state-link":
                        state.symlink_to(outside / "state.json")
                    else:
                        state.mkdir()
                result = invoke(sandbox, "install")
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("state", result.stderr)
                self.assertFalse((sandbox.root / "commands").exists())

    def test_state_write_does_not_follow_predictable_temporary_link(self) -> None:
        state_directory = self.path / "xdg/state/harness-kit"
        state_directory.mkdir(parents=True)
        canary = self.path / "canary"
        canary.write_text("protected\n")
        (state_directory / "state.tmp").symlink_to(canary)

        result = invoke(self.sandbox, "install", "--harness", "claude", "--component", "instructions")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(canary.read_text(), "protected\n")
        self.assertTrue((state_directory / "state.tmp").is_symlink())
        self.assertTrue((state_directory / "state.json").is_file())

    def test_state_write_refuses_substituted_temporary_and_preserves_it(self) -> None:
        state_directory = self.path / "xdg/state/harness-kit"
        state_directory.mkdir(parents=True)
        canary = self.path / "canary"
        canary.write_text("protected\n")
        # sitecustomize is copied-test subprocess instrumentation, not a CLI hook.
        (self.project / "src/sitecustomize.py").write_text(
            "import os\n"
            "original_open = os.open\n"
            "def substituted_open(path, flags, mode=0o777, *, dir_fd=None):\n"
            "    descriptor = original_open(path, flags, mode, dir_fd=dir_fd)\n"
            "    if isinstance(path, str) and path.startswith('.state-') and flags & os.O_CREAT:\n"
            "        os.unlink(path, dir_fd=dir_fd)\n"
            "        os.symlink(os.environ['STATE_TEMP_CANARY'], path, dir_fd=dir_fd)\n"
            "    return descriptor\n"
            "os.open = substituted_open\n"
        )

        result = invoke(
            self.sandbox,
            "install", "--harness", "claude", "--component", "instructions",
            environment_override={"STATE_TEMP_CANARY": str(canary)},
        )

        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("temporary was substituted", result.stderr)
        self.assertEqual(canary.read_text(), "protected\n")
        leftovers = list(state_directory.glob(".state-*.tmp"))
        self.assertEqual(len(leftovers), 1)
        self.assertTrue(leftovers[0].is_symlink())
        self.assertEqual(leftovers[0].resolve(), canary)
        self.assertFalse((state_directory / "state.json").exists())

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

    def test_managed_parent_symlinks_fail_closed_for_every_family(self) -> None:
        families = (
            (".claude", "claude", "instructions"),
            (".claude/agents", "claude", "agents"),
            (".claude/skills", "claude", "skills"),
            (".agents", "pi", "instructions"),
            (".agents/skills", "pi", "skills"),
            (".pi", "pi", "instructions"),
            (".pi/agent", "pi", "instructions"),
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
        families = (".claude", ".claude/agents", ".claude/skills", ".agents", ".agents/skills", ".pi", ".pi/agent")
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

    def test_install_conflicts_when_owned_link_target_changes(self) -> None:
        destination = self.path / "home/.agents/AGENTS.md"
        target_a = self.path / "target-a"
        target_b = self.project / "content/instructions/AGENTS.md"
        target_a.write_text("target A\n")
        destination.parent.mkdir(parents=True)
        destination.symlink_to(target_a)
        state = self.path / "xdg/state/harness-kit/state.json"
        state.parent.mkdir(parents=True)
        original_state = json.dumps({"links": {str(destination): str(target_a)}}) + "\n"
        state.write_text(original_state)
        original_a = target_a.read_text()

        preview = invoke(self.sandbox, "preview")
        self.assertEqual(preview.returncode, 2, preview.stderr)
        self.assertIn("[CONFLICT]", preview.stdout)
        self.assertNotIn("[UPDATE]", preview.stdout)
        self.assertEqual(state.read_text(), original_state)

        result = invoke(self.sandbox, "install")

        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("[CONFLICT]", result.stdout)
        self.assertNotIn("[UPDATE]", result.stdout)
        self.assertFalse((self.path / "commands").exists())
        self.assertTrue(destination.is_symlink())
        self.assertEqual(destination.resolve(), target_a.resolve())
        self.assertEqual(target_a.read_text(), original_a)
        self.assertEqual(state.read_text(), original_state)
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

        state = json.loads((self.path / "xdg/state/harness-kit/state.json").read_text())
        self.assertIn(str(destination), state["links"])

    def test_install_rejects_forged_unrelated_owned_destination_before_commands_or_mutation(self) -> None:
        settings = self.path / "home/.pi/agent/settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text('{"protected": true}\n')
        state = self.path / "xdg/state/harness-kit/state.json"
        state.parent.mkdir(parents=True)
        state.write_text(json.dumps({"links": {str(settings): str(self.project / "content/instructions/AGENTS.md")}}))

        result = invoke(self.sandbox, "install", "--harness", "claude", "--component", "instructions")

        self.assertEqual(result.returncode, 2)
        self.assertIn("invalid ownership state", result.stderr)
        self.assertEqual(settings.read_text(), '{"protected": true}\n')
        self.assertFalse((self.path / "commands").exists())
        self.assertFalse((self.path / "home/.claude/CLAUDE.md").exists())

    def test_install_rejects_malformed_owned_destinations_before_mutation(self) -> None:
        home = self.path / "home"
        malformed = (
            "relative/.claude/CLAUDE.md",
            str(home / ".claude/agents/../CLAUDE.md"),
            f"{home}/.claude/./CLAUDE.md",
            f"{home}/.claude//CLAUDE.md",
            f"{home}-other/.claude/CLAUDE.md",
            "",
            str(home / ".claude/CLAUDE.md") + "\0suffix",
            str(home / ".claude/agents/stale/ghost.md"),
            str(home / ".claude/skills/code-review/extra"),
            str(home / ".claude/agents/Scout.md"),
            str(home / ".claude/agents/scout.txt"),
            str(home / ".agents/skills/.code-review"),
        )
        state = self.path / "xdg/state/harness-kit/state.json"
        state.parent.mkdir(parents=True)
        target = str(self.project / "content/instructions/AGENTS.md")
        for destination in malformed:
            with self.subTest(destination=repr(destination)):
                state.write_text(json.dumps({"links": {destination: target}}))
                result = invoke(self.sandbox, "install", "--harness", "claude", "--component", "instructions")
                self.assertEqual(result.returncode, 2)
                self.assertIn("invalid ownership state", result.stderr)
                self.assertFalse((self.path / "commands").exists())
                self.assertFalse((home / ".claude/CLAUDE.md").exists())

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
        self.assertFalse((self.path / "xdg/state/harness-kit/state.json").exists())
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
        self.assertFalse((self.path / "xdg/state/harness-kit/state.json").exists())
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
        self.assertFalse((self.path / "xdg/state/harness-kit/state.json").exists())

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
