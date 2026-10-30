from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any

SOURCE_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = SOURCE_ROOT / "content/claude/statusline.sh"

ESC = "\033"
RST = f"{ESC}[0m"
SEP = f"{ESC}[90m | {RST}"
GIT_GREEN = f"{ESC}[38;5;76m"
GIT_YELLOW = f"{ESC}[38;5;178m"
GIT_BLUE = f"{ESC}[38;5;39m"
GIT_RED = f"{ESC}[38;5;196m"
MAGENTA = f"{ESC}[35m"
GREEN = f"{ESC}[32m"
YELLOW = f"{ESC}[33m"
RED = f"{ESC}[31m"
ORANGE = f"{ESC}[38;5;214m"
ICON = "\uf419"


@unittest.skipUnless(shutil.which("git") and shutil.which("jq"), "git and jq are required")
class StatuslineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        (self.root / "home").mkdir()
        self.environment = {
            "HOME": str(self.root / "home"),
            "PATH": os.environ["PATH"],
            "LC_ALL": "C",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_SYSTEM": "/dev/null",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.com",
        }
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.git("init", "-q", "-b", "main")
        self.commit("tracked.txt", "one\n")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def git(self, *arguments: str, cwd: Path | None = None, check: bool = True) -> str:
        result = subprocess.run(
            ["git", *arguments], cwd=cwd or self.repo, env=self.environment, text=True, capture_output=True, check=False,
        )
        if check and result.returncode != 0:
            raise AssertionError(f"git {' '.join(arguments)} failed: {result.stderr}")
        return result.stdout.strip()

    def commit(self, name: str, content: str) -> None:
        (self.repo / name).write_text(content)
        self.git("add", name)
        self.git("commit", "-q", "-m", f"update {name}")

    def run_statusline(
        self, payload: dict[str, Any] | None = None, *, cwd: Path | None = None,
        environment: dict[str, str] | None = None, **overrides: Any,
    ) -> str:
        data: dict[str, Any] = {
            "workspace": {"current_dir": str(cwd or self.repo)},
            "model": {"display_name": "Opus 5.5 (1M context)"},
            "effort": {"level": "medium"},
            "context_window": {"used_percentage": 12.5},
            "cost": {"total_cost_usd": 1.234},
        }
        data.update(overrides)
        if payload is not None:
            data = payload
        result = subprocess.run(
            ["bash", str(SCRIPT)], input=json.dumps(data), cwd=self.root, env=environment or self.environment,
            text=True, capture_output=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertTrue(result.stdout.endswith("\n"))
        self.assertEqual(result.stdout.count("\n"), 1, result.stdout)
        return result.stdout[:-1]

    def git_segment(self, **overrides: Any) -> str:
        return self.run_statusline(**overrides).split(SEP)[0]

    def test_exact_full_line(self) -> None:
        self.commit("tracked.txt", "two\n")
        self.git("remote", "add", "origin", str(self.root / "remote.git"))
        self.git("clone", "-q", "--bare", str(self.repo), str(self.root / "remote.git"), cwd=self.root)
        self.git("fetch", "-q", "origin")
        self.git("branch", "-q", "--set-upstream-to=origin/main")
        self.commit("a.txt", "a\n")
        self.commit("b.txt", "b\n")
        (self.repo / "staged.txt").write_text("staged\n")
        self.git("add", "staged.txt")
        for name in ("tracked.txt", "a.txt", "b.txt"):
            (self.repo / name).write_text("changed\n")
        (self.repo / "new.txt").write_text("new\n")
        line = self.run_statusline(context_window={"used_percentage": 64.9})
        self.assertEqual(
            line,
            f"{GIT_GREEN}{ICON} main {GIT_GREEN}⇡2 {GIT_YELLOW}+1 {GIT_YELLOW}!3 {GIT_BLUE}?1{RST}"
            f"{SEP}{MAGENTA}Opus 5.5 (1M context), medium{RST}"
            f"{SEP}{YELLOW}64%{RST} context used"
            f"{SEP}{ORANGE}$1.23{RST}",
        )

    def test_clean_branch(self) -> None:
        self.assertEqual(self.git_segment(), f"{GIT_GREEN}{ICON} main{RST}")

    def test_staged_unstaged_and_untracked_counts(self) -> None:
        self.commit("other.txt", "one\n")
        (self.repo / "staged-a.txt").write_text("a\n")
        (self.repo / "staged-b.txt").write_text("b\n")
        self.git("add", "staged-a.txt", "staged-b.txt")
        (self.repo / "tracked.txt").write_text("changed\n")
        (self.repo / "untracked-a.txt").write_text("a\n")
        (self.repo / "untracked-b.txt").write_text("b\n")
        (self.repo / "untracked-c.txt").write_text("c\n")
        (self.repo / ".gitignore").write_text("ignored.txt\n")
        (self.repo / "ignored.txt").write_text("ignored\n")
        self.assertEqual(
            self.git_segment(),
            f"{GIT_GREEN}{ICON} main {GIT_YELLOW}+2 {GIT_YELLOW}!1 {GIT_BLUE}?4{RST}",
        )

    def test_file_both_staged_and_unstaged_counts_twice(self) -> None:
        (self.repo / "tracked.txt").write_text("staged\n")
        self.git("add", "tracked.txt")
        (self.repo / "tracked.txt").write_text("staged then edited\n")
        self.assertEqual(self.git_segment(), f"{GIT_GREEN}{ICON} main {GIT_YELLOW}+1 {GIT_YELLOW}!1{RST}")

    def test_renamed_file_counts_as_staged(self) -> None:
        self.git("mv", "tracked.txt", "renamed.txt")
        self.assertEqual(self.git_segment(), f"{GIT_GREEN}{ICON} main {GIT_YELLOW}+1{RST}")

    def test_conflicts(self) -> None:
        self.git("checkout", "-q", "-b", "other")
        self.commit("tracked.txt", "other\n")
        self.git("checkout", "-q", "main")
        self.commit("tracked.txt", "main\n")
        self.git("merge", "-q", "other", check=False)
        self.assertEqual(self.git_segment(), f"{GIT_GREEN}{ICON} main {GIT_RED}~1{RST}")

    def test_ahead_and_behind_against_local_bare_remote(self) -> None:
        remote = self.root / "remote.git"
        self.commit("tracked.txt", "two\n")
        self.git("clone", "-q", "--bare", str(self.repo), str(remote), cwd=self.root)
        self.git("remote", "add", "origin", str(remote))
        self.git("fetch", "-q", "origin")
        self.git("branch", "-q", "--set-upstream-to=origin/main")
        self.assertEqual(self.git_segment(), f"{GIT_GREEN}{ICON} main{RST}")

        self.git("reset", "-q", "--hard", "HEAD~1")
        self.assertEqual(self.git_segment(), f"{GIT_GREEN}{ICON} main {GIT_GREEN}⇣1{RST}")

        self.commit("a.txt", "a\n")
        self.commit("b.txt", "b\n")
        self.assertEqual(self.git_segment(), f"{GIT_GREEN}{ICON} main {GIT_GREEN}⇣1{GIT_GREEN}⇡2{RST}")

        self.git("reset", "-q", "--hard", "origin/main")
        self.commit("c.txt", "c\n")
        self.assertEqual(self.git_segment(), f"{GIT_GREEN}{ICON} main {GIT_GREEN}⇡1{RST}")

    def test_detached_head_shows_short_oid(self) -> None:
        oid = self.git("rev-parse", "HEAD")
        self.git("checkout", "-q", "--detach")
        self.assertEqual(self.git_segment(), f"{GIT_GREEN}@{oid[:8]}{RST}")

    def test_long_branch_is_truncated(self) -> None:
        branch = "feature/abcdefghijklmnopqrstuvwxyz-0123456789"
        self.git("checkout", "-q", "-b", branch)
        self.assertEqual(self.git_segment(), f"{GIT_GREEN}{ICON} {branch[:12]}…{branch[-12:]}{RST}")
        exact = "f" * 32
        self.git("checkout", "-q", "-b", exact)
        self.assertEqual(self.git_segment(), f"{GIT_GREEN}{ICON} {exact}{RST}")

    def test_non_repository_omits_git_segment(self) -> None:
        outside = self.root / "plain"
        outside.mkdir()
        self.assertEqual(
            self.run_statusline(cwd=outside),
            f"{MAGENTA}Opus 5.5 (1M context), medium{RST}{SEP}{GREEN}12%{RST} context used{SEP}{ORANGE}$1.23{RST}",
        )

    def test_cwd_fallback_field(self) -> None:
        payload = {"cwd": str(self.repo), "model": {"display_name": "Opus"}}
        self.assertEqual(self.run_statusline(payload).split(SEP)[0], f"{GIT_GREEN}{ICON} main{RST}")

    def test_context_color_thresholds(self) -> None:
        outside = self.root / "plain"
        outside.mkdir()
        for value, color, shown in ((0, GREEN, "0"), (49.9, GREEN, "49"), (50, YELLOW, "50"), (79.99, YELLOW, "79"), (80, RED, "80"), (100, RED, "100")):
            with self.subTest(value=value):
                segments = self.run_statusline(cwd=outside, context_window={"used_percentage": value}).split(SEP)
                self.assertEqual(segments[1], f"{color}{shown}%{RST} context used")

    def test_missing_context_is_zero(self) -> None:
        outside = self.root / "plain"
        outside.mkdir()
        payload = {"workspace": {"current_dir": str(outside)}, "model": {"display_name": "Opus"}}
        self.assertEqual(self.run_statusline(payload), f"{MAGENTA}Opus{RST}{SEP}{GREEN}0%{RST} context used")

    def test_missing_effort_shows_model_only(self) -> None:
        outside = self.root / "plain"
        outside.mkdir()
        segments = self.run_statusline(cwd=outside, effort={}).split(SEP)
        self.assertEqual(segments[0], f"{MAGENTA}Opus 5.5 (1M context){RST}")

    def test_missing_model_omits_model_segment(self) -> None:
        outside = self.root / "plain"
        outside.mkdir()
        self.assertEqual(
            self.run_statusline(cwd=outside, model={}),
            f"{GREEN}12%{RST} context used{SEP}{ORANGE}$1.23{RST}",
        )

    def test_missing_cost_omits_cost_segment(self) -> None:
        outside = self.root / "plain"
        outside.mkdir()
        self.assertEqual(
            self.run_statusline(cwd=outside, cost={}),
            f"{MAGENTA}Opus 5.5 (1M context), medium{RST}{SEP}{GREEN}12%{RST} context used",
        )

    def test_cost_is_formatted_to_cents(self) -> None:
        outside = self.root / "plain"
        outside.mkdir()
        for value, shown in ((0, "$0.00"), (0.005, "$0.01"), (0.05, "$0.05"), (12.3, "$12.30"), (1234.567, "$1234.57")):
            with self.subTest(value=value):
                segments = self.run_statusline(cwd=outside, cost={"total_cost_usd": value}).split(SEP)
                self.assertEqual(segments[-1], f"{ORANGE}{shown}{RST}")

    def test_cost_ignores_comma_decimal_locale(self) -> None:
        outside = self.root / "plain"
        outside.mkdir()
        environment = {key: value for key, value in self.environment.items() if key != "LC_ALL"}
        environment.update({"LANG": "de_DE.UTF-8", "LC_NUMERIC": "de_DE.UTF-8"})
        segments = self.run_statusline(cwd=outside, environment=environment).split(SEP)
        self.assertEqual(segments[-1], f"{ORANGE}$1.23{RST}")

    def test_non_numeric_cost_is_omitted(self) -> None:
        outside = self.root / "plain"
        outside.mkdir()
        segments = self.run_statusline(cwd=outside, cost={"total_cost_usd": "1.23"}).split(SEP)
        self.assertEqual(len(segments), 2)

    def test_control_characters_in_fields_are_neutralized(self) -> None:
        outside = self.root / "plain"
        outside.mkdir()
        segments = self.run_statusline(cwd=outside, model={"display_name": "Opus\x1b[31m\x07\x7fX"}).split(SEP)
        self.assertEqual(segments[0], f"{MAGENTA}Opus [31m  X, medium{RST}")
        self.assertNotIn(ESC + "[31m", "".join(segments))

    def test_wrong_typed_field_does_not_shift_later_fields(self) -> None:
        outside = self.root / "plain"
        outside.mkdir()
        self.assertEqual(
            self.run_statusline(cwd=outside, effort="high", context_window={"used_percentage": 90}),
            f"{MAGENTA}Opus 5.5 (1M context){RST}{SEP}{RED}90%{RST} context used{SEP}{ORANGE}$1.23{RST}",
        )
        self.assertEqual(
            self.run_statusline(cwd=outside, workspace="oops", model="oops", context_window=[90]),
            f"{GREEN}0%{RST} context used{SEP}{ORANGE}$1.23{RST}",
        )

    def test_newlines_in_fields_do_not_shift_values(self) -> None:
        outside = self.root / "plain"
        outside.mkdir()
        segments = self.run_statusline(cwd=outside, model={"display_name": "Opus\nInjected"}).split(SEP)
        self.assertEqual(segments[0], f"{MAGENTA}Opus Injected, medium{RST}")

    def test_missing_jq_is_reported(self) -> None:
        empty_bin = self.root / "bin"
        empty_bin.mkdir()
        result = subprocess.run(
            ["/bin/bash", str(SCRIPT)], input="{}", env={**self.environment, "PATH": str(empty_bin)},
            text=True, capture_output=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "jq not found\n")

    def test_script_is_executable_and_parses(self) -> None:
        self.assertTrue(os.access(SCRIPT, os.X_OK))
        self.assertTrue(SCRIPT.read_text().startswith("#!/bin/bash\n"))
        result = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(shutil.which("shellcheck"), "shellcheck is not installed")
    def test_script_is_shellcheck_clean(self) -> None:
        result = subprocess.run(["shellcheck", str(SCRIPT)], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
