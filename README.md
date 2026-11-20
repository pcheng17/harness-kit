# harness-kit

One checkout for personal generic agents, cross-harness skills, Pi configuration, and a Claude Code status line.

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

The repository policy provides complete defaults. To customize an individual agent on one machine, create `$XDG_CONFIG_HOME/harness-kit/config.toml` (or `~/.config/harness-kit/config.toml` when `XDG_CONFIG_HOME` is unset) manually. Reload active harnesses afterward, for example `/reload` in Pi.

### Pi content and extensions

A full Pi install deploys content first, then installs missing extensions using the local `pi` command. The checkout's Pi package contains only the rendered agent definitions. To deploy skills and agent definitions without installing any extensions:

```bash
uv run harness-kit install --harness pi --component skills --component agents
```

To install or retry just the extensions:

```bash
uv run harness-kit install --harness pi --component extensions
```

Harness Kit requests `pi-subagents`, `pi-polish`, and the `@juicesharp` packages `rpiv-ask-user-question`, `rpiv-btw`, and `rpiv-todo` without version pins. Existing npm package entries in Pi's personal settings are kept as-is, including version pins and resource filters. `check` verifies registration, not runtime compatibility.

An unpinned install can select a release that your Pi cannot load. Use `pi install 'npm:package-name@<compatible-version>'` with the actual package name and version on that machine, then reload Pi. Harness Kit will leave the pin alone. If Pi reports an install failure, Harness Kit still attempts the other extensions and exits non-zero; content already installed is unaffected.

When upgrading an existing checkout, extensions previously loaded from its `node_modules` are now installed as separate Pi packages. If an older machine needs a specific release, register that pin with Pi before your next full Harness Kit install. The checkout no longer needs `npm ci` or `node_modules`.

Your rendered agents are usable by [`pi-subagents`](https://github.com/nicobailon/pi-subagents) versions that support package agent discovery. Harness Kit leaves your `subagents` settings user-managed.

## Commands

- `uv run harness-kit preview [--harness claude|pi|codex|all] [--component NAME]` prints the desired deployment without changing anything.
- `uv run harness-kit install [--harness claude|pi|codex|all] [--component NAME]` renders selected agents, deploys links and managed instruction sections, and registers selected Pi packages. Conflicting destinations are left untouched.
- `uv run harness-kit check [--harness claude|pi|codex|all] [--component NAME]` validates selected content and reports drift without mutating anything.

Components are `skills`, `agents`, `instructions`, `statusline` (Claude only), and `extensions` (Pi only). `--component` is repeatable; omit it to install every component for the selected harnesses. Skills-only operations link canonical skill directories directly (without rendering agents or running external harness commands). For example, install shared Pi/Codex skills with `uv run harness-kit install --harness codex --component skills`, or Claude agents and instructions with `uv run harness-kit install --harness claude --component agents --component instructions`.

### Agent installation by harness

The `agents` component uses each harness's supported distribution mechanism:

| Harness | Rendered agents | Installation mechanism |
| --- | --- | --- |
| Claude | `.generated/claude/agents/*.md` | Links into `~/.claude/agents/` |
| Pi | `.generated/pi/agents/*.md` | Registers this checkout as a Pi package with `pi install`; `package.json` exposes the rendered directory through `pi.subagents.agents` |
| Codex | `.generated/codex/agents/*.toml` | Links into `$CODEX_HOME/agents/` (default `~/.codex/agents/`) |

Pi package agents remain in this checkout. They are discovered through the package entry in `~/.pi/agent/settings.json` (or `$PI_CODING_AGENT_DIR/settings.json` if set to a directory inside `HOME`), so installing the Pi `agents` component intentionally does **not** copy or link them into `~/.pi/agent/agents/`. That directory remains available for user-local agents and overrides. Reload an active Pi session after installation.

Installation is stateless: it does not keep a separate ownership record or remove historical state. Skills are linked individually, allowing them to coexist with other skills; manually clean up links that are no longer desired.

### Global instructions

Harness Kit appends a section marked `BEGIN HARNESS KIT INSTRUCTIONS` and `END HARNESS KIT INSTRUCTIONS` to each selected global instructions file. Text outside those markers is yours and is preserved byte for byte. Running `install` again refreshes only that section; running `check` ignores changes outside it.

On upgrade, `preview` shows `MIGRATE` for an old symlink that resolves to this checkout's common instructions. `install` replaces the link itself with a regular file containing the managed section, without editing the link target. Links to another checkout, dangling links, other non-regular destinations, and ambiguous markers are conflicts. Resolve them manually before rerunning `install`.

### Claude status line

The `statusline` component only links `~/.claude/statusline.sh`. An existing unmanaged `~/.claude/statusline.sh` (a regular file or a symlink elsewhere) is reported as a conflict and never replaced; move it away first, then rerun `install`. Harness Kit never writes `~/.claude/settings.json`; enable the script there yourself:

```json
"statusLine": {"type": "command", "command": "~/.claude/statusline.sh"}
```

Until `statusLine.command` is `~/.claude/statusline.sh` (or its absolute path), `check` reports drift and `preview`/`install` print this hint. The settings file is only read (following a symlink if it is one); if it cannot be read or parsed, Harness Kit prints a warning, treats the status line as not configured, and still installs links.

## Layout

- `content/agents/`: generic declarative agents rendered for Claude, Pi, and Codex.
- `content/skills/`: canonical skills linked individually to Claude's `~/.claude/skills` and the shared Pi/Codex user directory `~/.agents/skills`.
- `content/claude/statusline.sh`: Claude Code status line script linked to `~/.claude/statusline.sh`. It prints one line (git status, model and effort, context usage, cost) and requires `jq`; the git segment uses a Nerd Font branch glyph.
- `content/instructions/AGENTS.md`: source of the managed sections in `~/.claude/CLAUDE.md`, `~/.agents/AGENTS.md`, `~/.pi/agent/AGENTS.md`, and `$CODEX_HOME/AGENTS.md` (default `~/.codex/AGENTS.md`). Codex reads a non-empty `$CODEX_HOME/AGENTS.override.md` instead, when present; Harness Kit leaves that user-owned override untouched and does not report it as drift.
- `.generated/`: disposable rendered agents. Codex agents are TOML files and install under `$CODEX_HOME/agents` (default `~/.codex/agents`). `CODEX_HOME` must be non-empty, absolute, strictly inside the physical `HOME`, contain no `.` or `..` components, and have no symlinked or non-directory ancestors.

Pi-specific agents have intentionally been removed. Generic agents are rendered into `.generated/pi/agents` and exposed through this checkout's Pi package.

## Agent definitions

Each `content/agents/*/agent.toml` declares only `name`, `description`, and tool capabilities. Harness Kit translates those capabilities with fixed adapter mappings; tool mappings are not policy-configurable.

## Policy

Checked-in `config.toml` supplies a concrete `model` and `effort` for every agent and each of Claude, Pi, and Codex. Missing defaults are invalid. The renderer translates `effort` to Claude `effort`, Pi `thinking`, and Codex `model_reasoning_effort`.

An optional `$XDG_CONFIG_HOME/harness-kit/config.toml` (falling back to `~/.config/harness-kit/config.toml`) is a partial override over those defaults. It may contain only known agents, known harnesses, and non-empty single-line string `model` and `effort` values:

```toml
[agents.researcher.pi]
model = "openai-codex/gpt-6-sol"
effort = "high"

[agents.researcher.codex]
model = "gpt-6-sol"
effort = "high"
```

Machine values take precedence over checked-in defaults; omitted values retain the checked-in value. Existing machine `policy.toml` files must be renamed to `config.toml`; the old name is not read. Model tiers, provider routing, and configurable tool mappings are not supported.
