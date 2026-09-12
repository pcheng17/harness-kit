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


class KitError(RuntimeError):
    pass


@dataclass(frozen=True)
class Agent:
    name: str
    description: str
    tier: str
    tools: tuple[str, ...]
    prompt: str
    claude: dict[str, Any]
    pi: dict[str, Any]


@dataclass(frozen=True)
class Link:
    destination: Path
    target: Path
    kind: str


@dataclass(frozen=True)
class Operation:
    action: str
    link: Link
    detail: str = ""


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


def load_catalog(harness: str, components: frozenset[str]) -> tuple[dict[str, Any], list[Agent]]:
    if "instructions" in components and not COMMON_INSTRUCTIONS.is_file():
        raise KitError(f"missing common instructions: {COMMON_INSTRUCTIONS}")
    if "agents" not in components:
        return {}, []

    policy = load_toml(ROOT / "policy.toml")
    agents: list[Agent] = []
    names: set[str] = set()
    for metadata_path in sorted((ROOT / "content/agents").glob("*/agent.toml")):
        data = load_toml(metadata_path)
        prompt_path = metadata_path.with_name("prompt.md")
        if not prompt_path.is_file():
            raise KitError(f"missing prompt: {prompt_path}")
        required = ("name", "description", "model_tier", "tools")
        missing = [field for field in required if field not in data]
        if missing:
            raise KitError(f"{metadata_path}: missing {', '.join(missing)}")
        name = data["name"]
        if not isinstance(name, str) or not name or name in names:
            raise KitError(f"{metadata_path}: agent name must be unique and non-empty")
        names.add(name)
        tier = data["model_tier"]
        tools = data["tools"]
        if not isinstance(data["description"], str) or not isinstance(tier, str) or not isinstance(tools, list) or not all(isinstance(tool, str) for tool in tools):
            raise KitError(f"{metadata_path}: invalid description, model_tier, or tools")
        agents.append(Agent(name, data["description"], tier, tuple(tools), prompt_path.read_text(), data.get("claude", {}), data.get("pi", {})))
    if not agents:
        raise KitError("no agents found")
    validate_catalog(policy, agents, harness)
    return policy, agents


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
            if provider not in pi_models or agent.tier not in pi_models[provider]:
                raise KitError(f"{agent.name}: unknown Pi provider/tier {provider!r}/{agent.tier!r}")
            for tool in agent.tools:
                if tool not in pi_tools:
                    raise KitError(f"{agent.name}: unknown tool capability {tool!r} for Pi")


def render(policy: dict[str, Any], agents: list[Agent], harness: str) -> dict[Path, str]:
    files: dict[Path, str] = {}
    for agent in agents:
        if harness in ("all", "claude"):
            claude = [
                "---", f"name: {agent.name}", f"description: {agent.description}",
                f"tools: {', '.join(policy['tools']['claude'][tool] for tool in agent.tools)}",
                f"model: {policy['models']['claude'][agent.tier]}",
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
            pi.append(f"thinking: {agent.pi.get('thinking', 'medium')}")
            if "isolated" in agent.pi:
                value = str(agent.pi["isolated"]).lower() if isinstance(agent.pi["isolated"], bool) else agent.pi["isolated"]
                pi.append(f"isolated: {value}")
            pi.extend(["---", "", agent.prompt.rstrip(), ""])
            files[GENERATED / "pi/agents" / f"{agent.name}.md"] = "\n".join(pi)
    return files


def materialize(files: dict[Path, str], harness: str) -> None:
    for selected in ("claude", "pi"):
        if harness not in ("all", selected):
            continue
        destination = GENERATED / selected
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
            if destination.exists():
                shutil.rmtree(require_relative_to(destination, ROOT))
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary.rename(destination)
        finally:
            shutil.rmtree(require_relative_to(temporary_root, ROOT), ignore_errors=True)


def desired_links(harness: str, agents: list[Agent], components: frozenset[str]) -> list[Link]:
    user_home = home()
    links: list[Link] = []
    if harness in ("all", "claude"):
        if "instructions" in components:
            links.append(Link(user_home / ".claude/CLAUDE.md", COMMON_INSTRUCTIONS, "common-instructions"))
        if "agents" in components:
            for agent in agents:
                agent_file = GENERATED / "claude/agents" / f"{agent.name}.md"
                links.append(Link(user_home / ".claude/agents" / agent_file.name, agent_file, "claude-agent"))
        if "skills" in components:
            for skill in sorted((ROOT / "content/skills").iterdir()):
                if skill.is_dir() and (skill / "SKILL.md").is_file():
                    links.append(Link(user_home / ".claude/skills" / skill.name, skill, "claude-skill"))
    if harness in ("all", "pi"):
        if "instructions" in components:
            links.extend((
                Link(user_home / ".agents/AGENTS.md", COMMON_INSTRUCTIONS, "common-instructions"),
                Link(user_home / ".pi/agent/AGENTS.md", COMMON_INSTRUCTIONS, "common-instructions"),
            ))
        if "skills" in components:
            for skill in sorted((ROOT / "content/skills").iterdir()):
                if skill.is_dir() and (skill / "SKILL.md").is_file():
                    links.append(Link(user_home / ".agents/skills" / skill.name, skill, "shared-skill"))
    return links


def validate_managed_ancestors(destination: Path) -> None:
    """Reject existing managed parents that could redirect a link mutation."""
    user_home = home()
    try:
        relative_parent = destination.parent.relative_to(user_home)
    except ValueError as error:
        raise KitError(f"managed destination is outside HOME: {destination}") from error
    parent = user_home
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
    path = operation.link.destination
    validate_managed_ancestors(path)
    exists = path.exists() or path.is_symlink()
    if operation.action == "create":
        if exists:
            raise KitError(f"refusing to create substituted destination: {path}")


def preview(
    harness: str,
    agents: list[Agent],
    components: frozenset[str] = COMPONENTS,
) -> list[Operation]:
    desired = desired_links(harness, agents, components)
    operations: list[Operation] = []
    for link in desired:
        validate_managed_ancestors(link.destination)
        current = link_target(link.destination)
        if not link.destination.exists() and not link.destination.is_symlink():
            operations.append(Operation("create", link))
        elif current == link.target.resolve():
            operations.append(Operation("noop", link))
        else:
            operations.append(Operation("conflict", link, "destination target differs"))
    return operations


def agent_execution_plan(harness: str, components: frozenset[str]) -> list[Operation]:
    if harness not in ("all", "pi") or "agents" not in components:
        return []
    return [
        Operation("render", Link(GENERATED / "pi/agents", ROOT / "content/agents", "generated-agents"), "render Pi agents"),
        Operation("npm ci", Link(ROOT / "node_modules", ROOT / "package-lock.json", "npm-dependencies"), "install npm dependencies"),
        Operation("pi install", Link(home() / ".pi/agent/settings.json", ROOT, "pi-package"), "register Pi package"),
    ]


def print_plan(operations: list[Operation]) -> None:
    for operation in operations:
        suffix = f" ({operation.detail})" if operation.detail else ""
        action = f"[{operation.action.upper()}]"
        print(f"{action:12} {operation.link.destination} -> {operation.link.target}{suffix}")


def verify_generated(files: dict[Path, str], harness: str) -> bool:
    if not all(path.is_file() and path.read_text() == content for path, content in files.items()):
        return False
    for selected in ("claude", "pi"):
        if harness in ("all", selected):
            root = GENERATED / selected
            expected = {path for path in files if path.is_relative_to(root)}
            actual = set(root.glob("**/*.md"))
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


def install(harness: str, components: frozenset[str], dry_run: bool) -> int:
    policy, agents = load_catalog(harness, components)
    files = render(policy, agents, harness) if agents else {}
    operations = preview(harness, agents, components)
    operations.extend(agent_execution_plan(harness, components))
    print_plan(operations)
    conflicts = [operation for operation in operations if operation.action == "conflict"]
    if conflicts:
        raise KitError("refusing to overwrite unmanaged destinations")
    if dry_run:
        return 0
    if "agents" in components:
        materialize(files, harness)
    if harness in ("all", "pi") and "agents" in components:
        run(["npm", "ci"])
        run(["pi", "install", str(ROOT)])
    for operation in operations:
        path = operation.link.destination
        if operation.action == "create":
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
    operations = preview(harness, agents, components)
    drift = ("agents" in components and not verify_generated(files, harness)) or any(operation.action != "noop" for operation in operations)
    if harness in ("all", "pi") and "agents" in components:
        settings = home() / ".pi/agent/settings.json"
        try:
            installed = str(ROOT) in json.loads(settings.read_text()).get("packages", [])
        except (OSError, ValueError, json.JSONDecodeError):
            installed = False
        drift = drift or not installed
    if drift:
        print("harness-kit is valid but not converged; run: uv run harness-kit install")
        print_plan(operations)
        return 1
    print("harness-kit is valid and converged")
    return 0


COMMAND_HELP = {
    "preview": "show what install would change, without touching the filesystem",
    "install": "deploy content into the harness(es)",
    "check": "exit non-zero if the harness(es) are not converged with content",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="harness-kit",
        description="Deploy shared agent, skill, and instruction content into supported harnesses.",
    )
    subcommands = parser.add_subparsers(dest="command", required=True, metavar="{preview,install,check}")
    for command in ("preview", "install", "check"):
        item = subcommands.add_parser(command, help=COMMAND_HELP[command], description=COMMAND_HELP[command])
        item.add_argument("--harness", choices=("all", "claude", "pi"), default="all", help="limit to this harness (default: all)")
        item.add_argument("--component", action="append", choices=("skills", "agents", "instructions"), help="deploy only this component (repeatable)")
        if command == "install":
            item.add_argument("--dry-run", action="store_true", help="print the plan without applying it")
    args = parser.parse_args(argv)
    components = frozenset(args.component) if args.component else COMPONENTS
    try:
        if args.command == "preview":
            policy, agents = load_catalog(args.harness, components)
            # Render validation is intentionally performed without writing output.
            if agents:
                render(policy, agents, args.harness)
            operations = preview(args.harness, agents, components)
            operations.extend(agent_execution_plan(args.harness, components))
            print_plan(operations)
            return 2 if any(operation.action == "conflict" for operation in operations) else 0
        if args.command == "install":
            return install(args.harness, components, args.dry_run)
        return check(args.harness, components)
    except KitError as error:
        print(f"harness-kit: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
