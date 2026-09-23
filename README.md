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

The repository policy provides complete defaults. To customize model mappings or individual agents on one machine, create an optional machine policy:

```bash
uv run harness-kit configure
```

This creates `$XDG_CONFIG_HOME/harness-kit/policy.toml` (or `~/.config/harness-kit/policy.toml` when `XDG_CONFIG_HOME` is unset) and never overwrites an existing file.

Reload active harnesses afterward, for example `/reload` in Pi.

### Pi subagents

The Pi configuration depends on the [`pi-subagents`](https://github.com/nicobailon/pi-subagents) extension. Harness Kit installs its custom Pi agents alongside the extension's built-in agents and leaves all `subagents` settings user-managed.

The narrowest invocation that installs the Pi package and agents is:

```bash
uv run harness-kit install --harness pi --component agents
```

## Commands

- `uv run harness-kit preview [--harness claude|pi|codex|all] [--component skills|agents|instructions]` prints the desired deployment without changing anything.
- `uv run harness-kit install [--harness claude|pi|codex|all] [--component skills|agents|instructions]` renders selected agents, installs Pi dependencies and package registration only when Pi agents are selected, and handles each selected destination as create, noop (already targeting the intended source), or conflict. Conflicts are never replaced; old or non-selected links must be removed manually.
- `uv run harness-kit check [--harness claude|pi|codex|all] [--component skills|agents|instructions]` validates selected content and reports drift without mutating anything.
- `uv run harness-kit configure` creates an optional machine-specific policy template and refuses to replace an existing one.

`--component` is repeatable; omit it to install every component. Skills-only operations link canonical skill directories directly (without rendering agents or running external harness commands). For example, install shared Pi/Codex skills with `uv run harness-kit install --harness codex --component skills`, or Claude agents and instructions with `uv run harness-kit install --harness claude --component agents --component instructions`.

### Agent installation by harness

The `agents` component uses each harness's supported distribution mechanism:

| Harness | Rendered agents | Installation mechanism |
| --- | --- | --- |
| Claude | `.generated/claude/agents/*.md` | Links into `~/.claude/agents/` |
| Pi | `.generated/pi/agents/*.md` | Registers this checkout as a Pi package with `pi install`; `package.json` exposes the rendered directory through `pi.subagents.agents` |
| Codex | `.generated/codex/agents/*.toml` | Links into `$CODEX_HOME/agents/` (default `~/.codex/agents/`) |

Pi package agents remain in this checkout. They are discovered through the package entry in `~/.pi/agent/settings.json`, so installing the Pi `agents` component intentionally does **not** copy or link them into `~/.pi/agent/agents/`. That directory remains available for user-local agents and overrides. Reload an active Pi session after installation.

Installation is stateless: it does not record ownership or remove historical state. Existing deployed link destinations are never replaced or removed. Skills are linked individually, allowing them to coexist with other skills; manually clean up links that are no longer desired.

## Layout

- `content/agents/`: generic declarative agents rendered for Claude, Pi, and Codex.
- `content/skills/`: canonical skills linked individually to Claude's `~/.claude/skills` and the shared Pi/Codex user directory `~/.agents/skills`.
- `content/instructions/AGENTS.md`: common global instructions deployed as `~/.claude/CLAUDE.md`, `~/.agents/AGENTS.md`, `~/.pi/agent/AGENTS.md`, and `$CODEX_HOME/AGENTS.md` (default `~/.codex/AGENTS.md`). Codex reads a non-empty `$CODEX_HOME/AGENTS.override.md` instead, when present; Harness Kit leaves that user-owned override untouched and does not report it as drift.
- `.generated/`: disposable rendered agents. Codex agents are TOML files and install under `$CODEX_HOME/agents` (default `~/.codex/agents`). `CODEX_HOME` must be non-empty, absolute, strictly inside the physical `HOME`, contain no `.` or `..` components, and have no symlinked or non-directory ancestors.

Pi-specific agents have intentionally been removed. Generic agents are rendered into `.generated/pi/agents` and exposed through this checkout's Pi package.

## Agent metadata

Each `content/agents/*/agent.toml` declares `name`, `description`, `model_tier`, `reasoning_effort`, and `tools`. `model_tier` resolves through each harness's policy mapping. The shared `reasoning_effort` is rendered as Claude `effort`, Pi `thinking`, and Codex `model_reasoning_effort`; `[claude].effort`, `[pi].thinking`, and `[codex].model_reasoning_effort` can override it for one harness. Codex model IDs resolve through `[models.codex]` and are rendered as `model` in its generated TOML; `[codex].model` can override that tier-mapped model for one agent.

## Machine policy

The checked-in `policy.toml` and agent metadata are complete defaults. If present, `$XDG_CONFIG_HOME/harness-kit/policy.toml` (falling back to `~/.config/harness-kit/policy.toml`) is deep-merged over the repository policy. A machine policy is a partial TOML document: omitted values continue to inherit repository defaults.

Concrete model mappings can vary by machine:

```toml
[models.pi.anthropic]
strong = "anthropic/claude-opus-5"
```

The optional `[agents.<name>]` tables override operational settings for one agent. Harness-specific subtables support the same fields as the corresponding metadata table:

```toml
[agents.debugger]
model_tier = "strong"
reasoning_effort = "high"

[agents.debugger.pi]
provider = "anthropic"

[agents.debugger.codex]
model = "gpt-5.6-sol"
```

In this example, Pi routes `debugger` through the machine's `anthropic` model mapping while Codex uses the exact model override. Unknown agents, unknown agent settings, and incompatible base/override value types are rejected. The machine policy may also override existing `[models]` and `[tools]` values or add a Pi provider mapping.
