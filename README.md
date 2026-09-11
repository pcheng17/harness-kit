# harness-kit

One checkout for personal generic agents, cross-harness skills, and Pi configuration.

## Bootstrap

```bash
git clone <your-repo-url> ~/dev/harness-kit
cd ~/dev/harness-kit
uv run harness-kit preview
uv run harness-kit install
```

After pulling changes:

```bash
git pull --ff-only
uv run harness-kit install
```

Reload active harnesses afterward, for example `/reload` in Pi.

## Commands

- `uv run harness-kit preview [--harness claude|pi|all] [--component skills|agents|instructions]` prints the desired deployment without changing anything.
- `uv run harness-kit install [--harness claude|pi|all] [--component skills|agents|instructions] [--dry-run]` renders selected agents, installs Pi dependencies and package registration only when Pi agents are selected, and creates only safe owned links. Add `--adopt-legacy` once to migrate links from the old `~/dev/skills` and `~/dev/pi-kit` checkouts.
- `uv run harness-kit check [--harness claude|pi|all] [--component skills|agents|instructions]` validates selected content and reports drift without mutating anything.

`--component` is repeatable; omit it to install every component. For example, install only shared skills with `uv run harness-kit install --component skills`, or Claude agents and instructions with `uv run harness-kit install --harness claude --component agents --component instructions`.

The installer stores ownership state under `~/.local/state/harness-kit/state.json`. It never replaces an unmanaged path. Skills are linked individually, allowing them to coexist with other skills.

## Layout

- `content/agents/`: generic declarative agents rendered for Claude and Pi.
- `content/skills/`: canonical skills shared through `~/.agents/skills` and Claude.
- `content/instructions/AGENTS.md`: common global instructions deployed as `~/.claude/CLAUDE.md`, `~/.agents/AGENTS.md`, and `~/.pi/agent/AGENTS.md`.
- `.generated/`: disposable rendered agents.

Pi-specific agents have intentionally been removed. Generic agents are rendered into `.generated/pi/agents` and exposed through this checkout's Pi package.
