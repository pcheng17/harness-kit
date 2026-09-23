"""Stateless build and deployment CLI for harness-kit."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
GENERATED = ROOT / ".generated"
COMMON_INSTRUCTIONS = ROOT / "content/instructions/AGENTS.md"
COMPONENTS = frozenset(("skills", "agents", "instructions"))
MACHINE_POLICY_TEMPLATE = """# Optional machine-specific overrides for harness-kit.
# Repository defaults remain active for every value omitted here.
#
# Example:
# [models.pi.anthropic]
# strong = "anthropic/claude-opus-5"
#
# [agents.debugger]
# model_tier = "strong"
# reasoning_effort = "high"
#
# [agents.debugger.pi]
# provider = "anthropic"
"""


class KitError(RuntimeError):
    pass


@dataclass(frozen=True)
class Agent:
    name: str
    description: str
    tier: str
    reasoning_effort: str
    tools: tuple[str, ...]
    prompt: str
    claude: dict[str, Any]
    pi: dict[str, Any]
    codex: dict[str, Any]


@dataclass(frozen=True)
class Link:
    destination: Path
    target: Path


@dataclass(frozen=True)
class Operation:
    action: str
    detail: str = ""
    link: Link | None = None


def home() -> Path:
    value = os.environ.get("HOME")
    if not value:
        raise KitError("HOME is not set")
    resolved = Path(value).expanduser().resolve()
    if len(resolved.parts) < 3:
        raise KitError(f"HOME resolves to a suspiciously shallow path: {resolved}")
    return resolved


def require_relative_to(path: Path, root: Path) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise KitError(f"refusing destructive operation outside {root}: {resolved}")
    return resolved


def load_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as file:
            return tomllib.load(file)
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise KitError(f"cannot read {path}: {error}") from error


def machine_policy_path() -> Path:
    if configured := os.environ.get("XDG_CONFIG_HOME"):
        root = Path(configured).expanduser()
        if not root.is_absolute():
            raise KitError("XDG_CONFIG_HOME must be absolute")
    else:
        root = home() / ".config"
    return root / "harness-kit/policy.toml"


def merge_tables(base: dict[str, Any], override: dict[str, Any], path: str = "policy") -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        location = f"{path}.{key}"
        if key not in merged:
            merged[key] = value
            continue
        existing = merged[key]
        if isinstance(existing, dict) and isinstance(value, dict):
            merged[key] = merge_tables(existing, value, location)
        elif isinstance(existing, dict) or isinstance(value, dict) or type(existing) is not type(value):
            raise KitError(f"{location} has incompatible base and machine-policy types")
        else:
            merged[key] = value
    return merged


def load_policy() -> dict[str, Any]:
    policy = load_toml(ROOT / "policy.toml")
    override_path = machine_policy_path()
    if not override_path.exists():
        return policy
    override = load_toml(override_path)
    unknown = sorted(set(override) - {"models", "tools", "agents"})
    if unknown:
        raise KitError(f"{override_path}: unknown top-level setting {unknown[0]!r}")
    return merge_tables(policy, override)


def validate_agent_override(name: str, override: Any) -> None:
    if not isinstance(override, dict):
        raise KitError(f"machine policy agent {name!r} must be a table")
    allowed = {"model_tier", "reasoning_effort", "claude", "pi", "codex"}
    unknown = sorted(set(override) - allowed)
    if unknown:
        raise KitError(f"machine policy agent {name!r}: unknown setting {unknown[0]!r}")
    harness_fields = {
        "claude": {"effort", "color"},
        "pi": {"provider", "thinking", "isolated"},
        "codex": {"model", "model_reasoning_effort"},
    }
    for harness, fields in harness_fields.items():
        if harness not in override:
            continue
        settings = override[harness]
        if not isinstance(settings, dict):
            raise KitError(f"machine policy agent {name!r}.{harness} must be a table")
        unknown_fields = sorted(set(settings) - fields)
        if unknown_fields:
            raise KitError(f"machine policy agent {name!r}.{harness}: unknown setting {unknown_fields[0]!r}")


def load_catalog(harness: str, components: frozenset[str]) -> tuple[dict[str, Any], list[Agent]]:
    if "instructions" in components and not COMMON_INSTRUCTIONS.is_file():
        raise KitError(f"missing common instructions: {COMMON_INSTRUCTIONS}")
    if "agents" not in components:
        return {}, []

    policy = load_policy()
    agent_overrides = policy.get("agents", {})
    if not isinstance(agent_overrides, dict):
        raise KitError("machine policy agents must be a table")
    for name, override in agent_overrides.items():
        validate_agent_override(name, override)

    agents: list[Agent] = []
    names: set[str] = set()
    for metadata_path in sorted((ROOT / "content/agents").glob("*/agent.toml")):
        data = load_toml(metadata_path)
        authored_name = data.get("name")
        if isinstance(authored_name, str) and authored_name in agent_overrides:
            data = merge_tables(data, agent_overrides[authored_name], f"agents.{authored_name}")
        prompt_path = metadata_path.with_name("prompt.md")
        if not prompt_path.is_file():
            raise KitError(f"missing prompt: {prompt_path}")
        required = ("name", "description", "model_tier", "reasoning_effort", "tools")
        missing = [field for field in required if field not in data]
        if missing:
            raise KitError(f"{metadata_path}: missing {', '.join(missing)}")
        name = data["name"]
        if not isinstance(name, str) or not name or name in names:
            raise KitError(f"{metadata_path}: agent name must be unique and non-empty")
        # Names become filenames in each generated harness tree. Keep them a
        # conservative identifier component rather than allowing path syntax.
        if name in (".", "..") or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for character in name):
            raise KitError(f"{metadata_path}: agent name must be a safe identifier component")
        names.add(name)
        tier = data["model_tier"]
        reasoning_effort = data["reasoning_effort"]
        tools = data["tools"]
        if not isinstance(data["description"], str) or not isinstance(tier, str) or not isinstance(reasoning_effort, str) or not reasoning_effort or not isinstance(tools, list) or not all(isinstance(tool, str) for tool in tools):
            raise KitError(f"{metadata_path}: invalid description, model_tier, reasoning_effort, or tools")
        agents.append(Agent(name, data["description"], tier, reasoning_effort, tuple(tools), prompt_path.read_text(), data.get("claude", {}), data.get("pi", {}), data.get("codex", {})))
    if not agents:
        raise KitError("no agents found")
    unknown_agents = sorted(set(agent_overrides) - names)
    if unknown_agents:
        raise KitError(f"machine policy references unknown agent {unknown_agents[0]!r}")
    validate_catalog(policy, agents, harness)
    return policy, agents


def validate_effort(agent: Agent, metadata: dict[str, Any], field: str, harness: str) -> None:
    value = metadata.get(field, agent.reasoning_effort)
    if not isinstance(value, str) or not value:
        raise KitError(f"{agent.name}: {harness} {field} must be a non-empty string")


def validate_catalog(policy: dict[str, Any], agents: list[Agent], harness: str) -> None:
    try:
        models = policy["models"]
        tools_by_harness = policy["tools"]
    except KeyError as error:
        raise KitError(f"policy.toml missing {error}") from error
    for agent in agents:
        if harness in ("all", "claude"):
            if not isinstance(agent.claude, dict):
                raise KitError(f"{agent.name}: Claude metadata must be a table")
            try:
                claude_models = models["claude"]
                claude_tools = tools_by_harness["claude"]
            except KeyError as error:
                raise KitError(f"policy.toml missing {error}") from error
            if agent.tier not in claude_models:
                raise KitError(f"{agent.name}: unknown model tier {agent.tier!r} for Claude")
            validate_effort(agent, agent.claude, "effort", "Claude")
            for tool in agent.tools:
                if tool not in claude_tools:
                    raise KitError(f"{agent.name}: unknown tool capability {tool!r} for Claude")
        if harness in ("all", "pi"):
            if not isinstance(agent.pi, dict):
                raise KitError(f"{agent.name}: Pi metadata must be a table")
            try:
                pi_models = models["pi"]
                pi_tools = tools_by_harness["pi"]
            except KeyError as error:
                raise KitError(f"policy.toml missing {error}") from error
            provider = agent.pi.get("provider", "codex")
            if not isinstance(provider, str) or provider not in pi_models or agent.tier not in pi_models[provider]:
                raise KitError(f"{agent.name}: unknown Pi provider/tier {provider!r}/{agent.tier!r}")
            validate_effort(agent, agent.pi, "thinking", "Pi")
            for tool in agent.tools:
                if tool not in pi_tools:
                    raise KitError(f"{agent.name}: unknown tool capability {tool!r} for Pi")
        if harness in ("all", "codex"):
            if not isinstance(agent.codex, dict):
                raise KitError(f"{agent.name}: Codex metadata must be a table")
            try:
                codex_models = models["codex"]
            except KeyError as error:
                raise KitError(f"policy.toml missing {error}") from error
            if agent.tier not in codex_models:
                raise KitError(f"{agent.name}: unknown model tier {agent.tier!r} for Codex")
            model = codex_models[agent.tier]
            if not isinstance(model, str) or not model:
                raise KitError(f"{agent.name}: invalid Codex model for tier {agent.tier!r}")
            if "model" in agent.codex and (not isinstance(agent.codex["model"], str) or not agent.codex["model"]):
                raise KitError(f"{agent.name}: Codex model must be a non-empty string")
            validate_effort(agent, agent.codex, "model_reasoning_effort", "Codex")


def toml_string(value: str) -> str:
    """Encode a TOML basic string without interpreting authored prompt text."""
    # JSON's string escaping is identical to TOML's basic-string escaping for
    # the characters relevant here, and ensure_ascii=False preserves Unicode.
    # TOML also forbids DEL (which JSON leaves unescaped).
    return json.dumps(value, ensure_ascii=False).replace("\x7f", "\\u007f")


def render(policy: dict[str, Any], agents: list[Agent], harness: str) -> dict[Path, str]:
    files: dict[Path, str] = {}
    for agent in agents:
        if harness in ("all", "codex"):
            codex = "\n".join((
                f"name = {toml_string(agent.name)}",
                f"description = {toml_string(agent.description)}",
                f"model = {toml_string(agent.codex.get('model', policy['models']['codex'][agent.tier]))}",
                f"model_reasoning_effort = {toml_string(agent.codex.get('model_reasoning_effort', agent.reasoning_effort))}",
                f"developer_instructions = {toml_string(agent.prompt)}",
                "",
            ))
            files[GENERATED / "codex/agents" / f"{agent.name}.toml"] = codex
        if harness in ("all", "claude"):
            claude = [
                "---", f"name: {agent.name}", f"description: {agent.description}",
                f"tools: {', '.join(policy['tools']['claude'][tool] for tool in agent.tools)}",
                f"model: {policy['models']['claude'][agent.tier]}",
                f"effort: {agent.claude.get('effort', agent.reasoning_effort)}",
            ]
            if color := agent.claude.get("color"):
                claude.append(f"color: {color}")
            claude.extend(["---", "", agent.prompt.rstrip(), ""])
            files[GENERATED / "claude/agents" / f"{agent.name}.md"] = "\n".join(claude)
        if harness in ("all", "pi"):
            provider = agent.pi.get("provider", "codex")
            pi = [
                "---", f"name: {agent.name}", f"description: {agent.description}",
                f"tools: {', '.join(policy['tools']['pi'][tool] for tool in agent.tools)}",
                f"model: {policy['models']['pi'][provider][agent.tier]}",
            ]
            pi.append(f"thinking: {agent.pi.get('thinking', agent.reasoning_effort)}")
            if "isolated" in agent.pi:
                value = str(agent.pi["isolated"]).lower() if isinstance(agent.pi["isolated"], bool) else agent.pi["isolated"]
                pi.append(f"isolated: {value}")
            pi.extend(["---", "", agent.prompt.rstrip(), ""])
            files[GENERATED / "pi/agents" / f"{agent.name}.md"] = "\n".join(pi)
    return files


def validate_generated_destination(destination: Path) -> None:
    """Reject generated paths whose existing ancestors can redirect writes."""
    try:
        relative = destination.relative_to(ROOT)
    except ValueError as error:
        raise KitError(f"generated destination is outside repository: {destination}") from error
    current = ROOT
    if current.is_symlink() or not current.is_dir():
        raise KitError(f"refusing unsafe repository root: {current}")
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise KitError(f"refusing symlinked generated ancestor: {current}")
        if current.exists() and not current.is_dir():
            raise KitError(f"refusing non-directory generated ancestor: {current}")


def materialize(files: dict[Path, str], harness: str) -> None:
    selected_harnesses = [selected for selected in ("claude", "pi", "codex") if harness in ("all", selected)]
    # Preflight every selected tree before creating any replacement or output.
    # In particular, mkdir/rename must never follow a symlinked .generated.
    destinations = {selected: GENERATED / selected for selected in selected_harnesses}
    for destination in destinations.values():
        validate_generated_destination(destination)
    for selected in selected_harnesses:
        destination = destinations[selected]
        temporary_root = Path(tempfile.mkdtemp(prefix="harness-kit-", dir=ROOT))
        temporary = temporary_root / selected
        try:
            temporary.mkdir()
            for output, content in files.items():
                if output.is_relative_to(destination):
                    relative = output.relative_to(destination)
                    generated = temporary / relative
                    generated.parent.mkdir(parents=True, exist_ok=True)
                    generated.write_text(content)
            # Revalidate immediately before the destructive replacement and
            # again before rename so a changed ancestor fails closed.
            validate_generated_destination(destination)
            if destination.exists():
                shutil.rmtree(require_relative_to(destination, ROOT))
            validate_generated_destination(destination)
            destination.parent.mkdir(parents=True, exist_ok=True)
            validate_generated_destination(destination)
            temporary.rename(destination)
        finally:
            shutil.rmtree(require_relative_to(temporary_root, ROOT), ignore_errors=True)


def codex_home() -> Path:
    """Return a Codex home that is strictly contained by the physical HOME."""
    user_home = home()
    value = os.environ.get("CODEX_HOME")
    if value is None:
        resolved = user_home / ".codex"
    elif not value:
        raise KitError("CODEX_HOME must not be empty")
    else:
        # Inspect the raw expanded spelling first. pathlib removes dot
        # components while constructing a Path, so checking candidate.parts
        # cannot distinguish an authored "." or ".." from a normalized path.
        expanded = os.path.expanduser(value)
        if any(component in (".", "..") for component in expanded.split(os.sep)):
            raise KitError("CODEX_HOME must not contain dot path components")
        candidate = Path(expanded)
        if not candidate.is_absolute():
            raise KitError("CODEX_HOME must be an absolute path")
        resolved = Path(os.path.abspath(candidate))
    if resolved == user_home or len(resolved.parts) <= len(user_home.parts):
        raise KitError(f"CODEX_HOME resolves to a suspiciously shallow path: {resolved}")
    try:
        resolved.relative_to(user_home)
    except ValueError as error:
        raise KitError(f"CODEX_HOME must be within HOME: {resolved}") from error
    # Check every existing component, including ancestors before CODEX_HOME.
    # Do not use resolve() here: symlink substitution is precisely what must
    # be rejected rather than silently normalized.
    current = user_home
    for component in resolved.relative_to(user_home).parts:
        current /= component
        if current.is_symlink():
            raise KitError(f"refusing CODEX_HOME with symlinked ancestor: {current}")
        if current.exists() and not current.is_dir():
            raise KitError(f"refusing CODEX_HOME with non-directory ancestor: {current}")
    return resolved


def shared_skill_links(user_home: Path) -> list[Link]:
    """Build the single user-level skill family shared by Pi and Codex."""
    return [
        Link(user_home / ".agents/skills" / skill.name, skill)
        for skill in sorted((ROOT / "content/skills").iterdir())
        if skill.is_dir() and (skill / "SKILL.md").is_file()
    ]


def desired_links(harness: str, agents: list[Agent], components: frozenset[str]) -> list[Link]:
    user_home = home()
    links: list[Link] = []
    if harness in ("all", "codex"):
        if "instructions" in components:
            destination_root = codex_home()
            links.append(Link(destination_root / "AGENTS.md", COMMON_INSTRUCTIONS))
        if "agents" in components:
            destination_root = codex_home() / "agents"
            for agent in agents:
                agent_file = GENERATED / "codex/agents" / f"{agent.name}.toml"
                links.append(Link(destination_root / agent_file.name, agent_file))
    if harness in ("all", "claude"):
        if "instructions" in components:
            links.append(Link(user_home / ".claude/CLAUDE.md", COMMON_INSTRUCTIONS))
        if "agents" in components:
            for agent in agents:
                agent_file = GENERATED / "claude/agents" / f"{agent.name}.md"
                links.append(Link(user_home / ".claude/agents" / agent_file.name, agent_file))
        if "skills" in components:
            for skill in sorted((ROOT / "content/skills").iterdir()):
                if skill.is_dir() and (skill / "SKILL.md").is_file():
                    links.append(Link(user_home / ".claude/skills" / skill.name, skill))
    if harness in ("all", "pi", "codex"):
        # Pi and Codex intentionally consume the same user-level skill links.
        if "skills" in components:
            links.extend(shared_skill_links(user_home))
    if harness in ("all", "pi"):
        if "instructions" in components:
            links.extend((
                Link(user_home / ".agents/AGENTS.md", COMMON_INSTRUCTIONS),
                Link(user_home / ".pi/agent/AGENTS.md", COMMON_INSTRUCTIONS),
            ))
    return links


def validate_managed_ancestors(destination: Path, managed_root: Path | None = None) -> None:
    """Reject existing managed parents that could redirect a link mutation."""
    if managed_root is None:
        managed_root = home()
    try:
        relative_parent = destination.parent.relative_to(managed_root)
    except ValueError as error:
        raise KitError(f"managed destination is outside its safety boundary: {destination}") from error
    parent = managed_root
    if parent.is_symlink():
        raise KitError(f"refusing managed destination with symlinked ancestor: {parent}")
    if parent.exists() and not parent.is_dir():
        raise KitError(f"refusing managed destination with non-directory ancestor: {parent}")
    for part in relative_parent.parts:
        parent /= part
        if parent.is_symlink():
            raise KitError(f"refusing managed destination with symlinked ancestor: {parent}")
        if parent.exists() and not parent.is_dir():
            raise KitError(f"refusing managed destination with non-directory ancestor: {parent}")


def link_target(path: Path) -> Path | None:
    if not path.is_symlink():
        return None
    return (path.parent / os.readlink(path)).resolve()


def validate_operation_preconditions(operation: Operation) -> None:
    """Recheck the plan's filesystem observations immediately before mutation."""
    if operation.link is None:
        return
    path = operation.link.destination
    validate_managed_ancestors(path)
    exists = path.exists() or path.is_symlink()
    if operation.action == "create":
        if exists:
            raise KitError(f"refusing to create substituted destination: {path}")


def link_operations(harness: str, agents: list[Agent], components: frozenset[str]) -> list[Operation]:
    operations: list[Operation] = []
    for link in desired_links(harness, agents, components):
        validate_managed_ancestors(link.destination)
        current = link_target(link.destination)
        if not link.destination.exists() and not link.destination.is_symlink():
            operations.append(Operation("create", link=link))
        elif current == link.target.resolve():
            operations.append(Operation("noop", link=link))
        else:
            operations.append(Operation("conflict", "destination target differs", link))
    return operations


def read_pi_settings(path: Path) -> dict[str, Any]:
    validate_managed_ancestors(path)
    if path.is_symlink():
        raise KitError(f"refusing symlinked Pi settings: {path}")
    if not path.exists():
        return {}
    if not path.is_file():
        raise KitError(f"refusing non-file Pi settings: {path}")
    try:
        settings = json.loads(path.read_text())
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise KitError(f"cannot read Pi settings {path}: {error}") from error
    if not isinstance(settings, dict):
        raise KitError(f"Pi settings must contain a JSON object: {path}")
    return settings


def install_plan(harness: str, agents: list[Agent], components: frozenset[str]) -> list[Operation]:
    """The ordered Install plan: generation, Pi bootstrap, then links."""
    operations: list[Operation] = []
    if "agents" in components:
        generated_paths = [GENERATED / selected / "agents" for selected in ("claude", "pi", "codex") if harness in ("all", selected)]
        operations.append(Operation("render", f"generate selected agent trees at {', '.join(map(str, generated_paths))}"))
        if harness in ("all", "pi"):
            operations.extend((
                Operation("npm ci", "install npm dependencies"),
                Operation("pi install", "register Pi package"),
            ))
    operations.extend(link_operations(harness, agents, components))
    return operations


def print_plan(operations: list[Operation]) -> None:
    for operation in operations:
        suffix = f" ({operation.detail})" if operation.detail else ""
        action = f"[{operation.action.upper()}]"
        if operation.link is not None:
            print(f"{action:12} {operation.link.destination} -> {operation.link.target}{suffix}")
        else:
            print(f"{action:12} {operation.detail}")


def validate_generated_trees(harness: str) -> None:
    """Reject selected generated trees that could redirect reads or writes."""
    for selected in ("claude", "pi", "codex"):
        if harness in ("all", selected):
            validate_generated_destination(GENERATED / selected / "agents")


def verify_generated(files: dict[Path, str], harness: str) -> bool:
    validate_generated_trees(harness)
    if not all(path.is_file() and not path.is_symlink() and path.read_text() == content for path, content in files.items()):
        return False
    for selected in ("claude", "pi", "codex"):
        if harness in ("all", selected):
            root = GENERATED / selected
            expected = {path for path in files if path.is_relative_to(root)}
            extension = "*.toml" if selected == "codex" else "*.md"
            actual = set(root.glob(f"**/{extension}"))
            if actual != expected:
                return False
    return True


def run(command: list[str]) -> None:
    try:
        subprocess.run(command, cwd=ROOT, check=True)
    except FileNotFoundError as error:
        raise KitError(f"required command not found: {command[0]}") from error
    except subprocess.CalledProcessError as error:
        raise KitError(f"external command failed ({error.returncode}): {' '.join(command)}") from error


def install(harness: str, components: frozenset[str]) -> int:
    policy, agents = load_catalog(harness, components)
    files = render(policy, agents, harness) if agents else {}
    operations = install_plan(harness, agents, components)
    print_plan(operations)
    if any(operation.action == "conflict" for operation in operations):
        raise KitError("refusing to overwrite unmanaged destinations")
    for operation in operations:
        if operation.action == "render":
            materialize(files, harness)
        elif operation.action == "npm ci":
            run(["npm", "ci"])
        elif operation.action == "pi install":
            run(["pi", "install", str(ROOT)])
        elif operation.action == "create":
            validate_operation_preconditions(operation)
            assert operation.link is not None
            path = operation.link.destination
            # Revalidate after any preceding operation and immediately before
            # mkdir/symlink, including the entire HOME-to-destination chain.
            validate_operation_preconditions(operation)
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                path.symlink_to(operation.link.target)
            except FileExistsError as error:
                raise KitError(f"refusing to replace substituted destination: {path}") from error
    return 0


def check(harness: str, components: frozenset[str]) -> int:
    policy, agents = load_catalog(harness, components)
    files = render(policy, agents, harness) if agents else {}
    operations = link_operations(harness, agents, components)
    drift = ("agents" in components and not verify_generated(files, harness)) or any(operation.action != "noop" for operation in operations)
    if harness in ("all", "pi") and "agents" in components:
        settings = read_pi_settings(home() / ".pi/agent/settings.json")
        packages = settings.get("packages", [])
        installed = isinstance(packages, list) and str(ROOT) in packages
        drift = drift or not installed
    if drift:
        print("harness-kit is valid but not converged; run: uv run harness-kit install")
        print_plan(operations)
        return 1
    print("harness-kit is valid and converged")
    return 0


def configure() -> int:
    destination = machine_policy_path()
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("x") as file:
            file.write(MACHINE_POLICY_TEMPLATE)
    except FileExistsError as error:
        raise KitError(f"machine policy already exists: {destination}") from error
    except OSError as error:
        raise KitError(f"cannot create {destination}: {error}") from error
    print(f"Created optional machine policy: {destination}")
    return 0


COMMAND_HELP = {
    "preview": "show what install would change, without touching the filesystem",
    "install": "deploy content into the harness(es)",
    "check": "exit non-zero if the harness(es) are not converged with content",
    "configure": "create an optional machine-specific policy file",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="harness-kit",
        description="Deploy shared agent, skill, and instruction content into supported harnesses.",
    )
    subcommands = parser.add_subparsers(dest="command", required=True, metavar="{preview,install,check,configure}")
    for command in ("preview", "install", "check"):
        item = subcommands.add_parser(command, help=COMMAND_HELP[command], description=COMMAND_HELP[command])
        item.add_argument("--harness", choices=("all", "claude", "pi", "codex"), default="all", help="limit to this harness (default: all)")
        item.add_argument("--component", action="append", choices=("skills", "agents", "instructions"), help="deploy only this component (repeatable)")
    subcommands.add_parser("configure", help=COMMAND_HELP["configure"], description=COMMAND_HELP["configure"])
    args = parser.parse_args(argv)
    try:
        if args.command == "configure":
            return configure()
        components = frozenset(args.component) if args.component else COMPONENTS
        if args.command == "preview":
            policy, agents = load_catalog(args.harness, components)
            # Render validation is intentionally performed without writing output.
            if agents:
                render(policy, agents, args.harness)
                if "agents" in components:
                    validate_generated_trees(args.harness)
            operations = install_plan(args.harness, agents, components)
            print_plan(operations)
            return 2 if any(operation.action == "conflict" for operation in operations) else 0
        if args.command == "install":
            return install(args.harness, components)
        return check(args.harness, components)
    except KitError as error:
        print(f"harness-kit: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
