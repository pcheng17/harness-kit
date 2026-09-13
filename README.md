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

- `uv run harness-kit preview [--harness claude|pi|codex|all] [--component skills|agents|instructions]` prints the desired deployment without changing anything.
- `uv run harness-kit install [--harness claude|pi|codex|all] [--component skills|agents|instructions]` renders selected agents, installs Pi dependencies and package registration only when Pi agents are selected, and handles each selected destination as create, noop (already targeting the intended source), or conflict. Conflicts are never replaced; old or non-selected links must be removed manually.
- `uv run harness-kit check [--harness claude|pi|codex|all] [--component skills|agents|instructions]` validates selected content and reports drift without mutating anything.

`--component` is repeatable; omit it to install every component. Skills-only operations link canonical skill directories directly (without rendering agents or running external harness commands). For example, install shared Pi/Codex skills with `uv run harness-kit install --harness codex --component skills`, or Claude agents and instructions with `uv run harness-kit install --harness claude --component agents --component instructions`.

Installation is stateless: it does not record ownership or remove historical state. Existing deployed link destinations are never replaced or removed. Skills are linked individually, allowing them to coexist with other skills; manually clean up links that are no longer desired.

## Layout

- `content/agents/`: generic declarative agents rendered for Claude, Pi, and Codex.
- `content/skills/`: canonical skills linked individually to Claude's `~/.claude/skills` and the shared Pi/Codex user directory `~/.agents/skills`.
- `content/instructions/AGENTS.md`: common global instructions deployed as `~/.claude/CLAUDE.md`, `~/.agents/AGENTS.md`, and `~/.pi/agent/AGENTS.md`.
- `.generated/`: disposable rendered agents. Codex agents are TOML files and install under `$CODEX_HOME/agents` (default `~/.codex/agents`). `CODEX_HOME` must be non-empty, absolute, strictly inside the physical `HOME`, contain no `.` or `..` components, and have no symlinked or non-directory ancestors.

Pi-specific agents have intentionally been removed. Generic agents are rendered into `.generated/pi/agents` and exposed through this checkout's Pi package.

## Agent metadata

Each `content/agents/*/agent.toml` declares `name`, `description`, `model_tier`, `reasoning_effort`, and `tools`. `model_tier` resolves through each harness's policy mapping. The shared `reasoning_effort` is rendered as Claude `effort`, Pi `thinking`, and Codex `model_reasoning_effort`; `[claude].effort`, `[pi].thinking`, and `[codex].model_reasoning_effort` can override it for one harness. Codex model IDs resolve through `[models.codex]` and are rendered as `model` in its generated TOML; `[codex].model` can override that tier-mapped model for one agent.
