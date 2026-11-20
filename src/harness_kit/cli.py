"""Stateless build and deployment CLI for harness-kit."""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import stat
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
INSTRUCTIONS_START = b"<!-- BEGIN HARNESS KIT INSTRUCTIONS -->"
INSTRUCTIONS_END = b"<!-- END HARNESS KIT INSTRUCTIONS -->"
INSTRUCTION_MARKERS = re.compile(rb"(?m)^(" + INSTRUCTIONS_START + b"|" + INSTRUCTIONS_END + rb")\r?(?:\n|$)")
CLAUDE_STATUSLINE = ROOT / "content/claude/statusline.sh"
STATUSLINE_COMMAND = "~/.claude/statusline.sh"
STATUSLINE_HINT = (
    'hint: harness-kit never edits ~/.claude/settings.json; to enable the status line, set '
    '"statusLine": {"type": "command", "command": "~/.claude/statusline.sh"} there yourself'
)
COMPONENT_CHOICES = ("skills", "agents", "instructions", "statusline", "extensions")
PI_EXTENSIONS = (
    "npm:pi-subagents",
    "npm:pi-polish",
    "npm:@juicesharp/rpiv-ask-user-question",
    "npm:@juicesharp/rpiv-btw",
    "npm:@juicesharp/rpiv-todo",
)
COMPONENTS = frozenset(COMPONENT_CHOICES)
CAPABILITY_TOOLS = {
    "claude": {"read": "Read", "grep": "Grep", "find": "Glob", "bash": "Bash", "edit": "Edit", "write": "Write"},
    "pi": {"read": "read", "grep": "grep", "find": "find", "bash": "bash", "edit": "edit", "write": "write"},
}
HARNESSES = ("claude", "pi", "codex")
POLICY_FIELDS = ("model", "effort")


class KitError(RuntimeError):
    pass


@dataclass(frozen=True)
class Agent:
    name: str
    description: str
    tools: tuple[str, ...]
    prompt: str


@dataclass(frozen=True)
class Link:
    destination: Path
    target: Path


@dataclass(frozen=True)
class InstructionSnapshot:
    device: int
    inode: int
    mode: int
    content: bytes | str


@dataclass(frozen=True)
class InstructionWrite:
    destination: Path
    content: bytes
    original: InstructionSnapshot | None = None


@dataclass(frozen=True)
class Operation:
    action: str
    detail: str = ""
    link: Link | None = None
    source: str | None = None
    instruction: InstructionWrite | None = None


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
    configured = os.environ.get("XDG_CONFIG_HOME")
    root = Path(configured) if configured else None
    if root is None or not root.is_absolute():
        root = home() / ".config"
    return root / "harness-kit/config.toml"


def load_machine_policy() -> dict[str, Any]:
    path = machine_policy_path()
    if not path.exists() and not path.is_symlink():
        return {}
    policy = load_toml(path)
    unknown = sorted(set(policy) - {"agents"})
    if unknown:
        raise KitError(f"{path}: unknown top-level setting {unknown[0]!r}")
    agents = policy.get("agents", {})
    if not isinstance(agents, dict):
        raise KitError(f"{path}: agents must be a table")
    return agents


def validate_policy_value(value: Any, location: str) -> None:
    # Models and effort are interpolated into YAML front matter as single lines.
    if not isinstance(value, str) or not value.strip() or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise KitError(f"{location} must be a non-empty single-line string")


def validate_policy_agents(
    settings_by_agent: dict[str, Any], names: list[str], location: Path, *, complete: bool,
) -> None:
    unknown_agents = sorted(set(settings_by_agent) - set(names))
    if unknown_agents:
        raise KitError(f"{location}: unknown agent {unknown_agents[0]!r}")
    selected = names if complete else list(settings_by_agent)
    for name in selected:
        harnesses = settings_by_agent.get(name)
        if complete and not isinstance(harnesses, dict):
            raise KitError(f"{location}: missing defaults for agent {name!r}")
        if not isinstance(harnesses, dict):
            raise KitError(f"{location}: agent {name!r} must be a table")
        if complete:
            missing = [harness for harness in HARNESSES if harness not in harnesses]
            if missing:
                raise KitError(f"{location}: missing defaults for {name!r}.{missing[0]}")
        unknown_harnesses = sorted(set(harnesses) - set(HARNESSES))
        if unknown_harnesses:
            raise KitError(f"{location}: agent {name!r}: unknown harness {unknown_harnesses[0]!r}")
        selected_harnesses = HARNESSES if complete else harnesses
        for harness in selected_harnesses:
            settings = harnesses[harness]
            if not isinstance(settings, dict):
                raise KitError(f"{location}: {name!r}.{harness} must be a table")
            if complete and set(settings) != set(POLICY_FIELDS):
                raise KitError(f"{location}: {name!r}.{harness} must contain only model and effort")
            unknown_fields = sorted(set(settings) - set(POLICY_FIELDS))
            if unknown_fields:
                raise KitError(f"{location}: {name!r}.{harness}: unknown setting {unknown_fields[0]!r}")
            for field in POLICY_FIELDS:
                if field in settings:
                    validate_policy_value(settings[field], f"{location}: {name!r}.{harness} {field}")


def merge_machine_policy(policy: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    merged = {"agents": {name: dict(settings) for name, settings in policy["agents"].items()}}
    for name, harnesses in overrides.items():
        for harness, values in harnesses.items():
            merged["agents"][name][harness] = {**merged["agents"][name][harness], **values}
    return merged


def load_catalog(harness: str, components: frozenset[str]) -> tuple[dict[str, Any], list[Agent]]:
    if "instructions" in components and not COMMON_INSTRUCTIONS.is_file():
        raise KitError(f"missing common instructions: {COMMON_INSTRUCTIONS}")
    if "statusline" in components and harness in ("all", "claude") and not CLAUDE_STATUSLINE.is_file():
        raise KitError(f"missing Claude status line script: {CLAUDE_STATUSLINE}")
    if "agents" not in components:
        return {}, []

    policy = load_toml(ROOT / "config.toml")
    agent_overrides = load_machine_policy()

    agents: list[Agent] = []
    names: set[str] = set()
    for metadata_path in sorted((ROOT / "content/agents").glob("*/agent.toml")):
        data = load_toml(metadata_path)
        prompt_path = metadata_path.with_name("prompt.md")
        if not prompt_path.is_file():
            raise KitError(f"missing prompt: {prompt_path}")
        required = ("name", "description", "tools")
        missing = [field for field in required if field not in data]
        if missing:
            raise KitError(f"{metadata_path}: missing {', '.join(missing)}")
        unknown = sorted(set(data) - set(required))
        if unknown:
            raise KitError(f"{metadata_path}: unknown setting {unknown[0]!r}")
        name = data["name"]
        if not isinstance(name, str) or not name or name in names:
            raise KitError(f"{metadata_path}: agent name must be unique and non-empty")
        # Names become filenames in each generated harness tree. Keep them a
        # conservative identifier component rather than allowing path syntax.
        if name in (".", "..") or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for character in name):
            raise KitError(f"{metadata_path}: agent name must be a safe identifier component")
        names.add(name)
        tools = data["tools"]
        if not isinstance(data["description"], str) or not isinstance(tools, list) or not all(isinstance(tool, str) for tool in tools):
            raise KitError(f"{metadata_path}: invalid description or tools")
        agents.append(Agent(name, data["description"], tuple(tools), prompt_path.read_text()))
    if not agents:
        raise KitError("no agents found")
    validate_policy_agents(agent_overrides, [agent.name for agent in agents], machine_policy_path(), complete=False)
    validate_catalog(policy, agents)
    return merge_machine_policy(policy, agent_overrides), agents


def validate_catalog(policy: dict[str, Any], agents: list[Agent]) -> None:
    if set(policy) != {"agents"} or not isinstance(policy["agents"], dict):
        raise KitError("config.toml must contain only an agents table")
    validate_policy_agents(policy["agents"], [agent.name for agent in agents], ROOT / "config.toml", complete=True)
    for agent in agents:
        for harness in CAPABILITY_TOOLS:
            for tool in agent.tools:
                if tool not in CAPABILITY_TOOLS[harness]:
                    raise KitError(f"{agent.name}: unknown tool capability {tool!r} for {harness.title()}")


def toml_string(value: str) -> str:
    """Encode a TOML basic string without interpreting authored prompt text."""
    # JSON's string escaping is identical to TOML's basic-string escaping for
    # the characters relevant here, and ensure_ascii=False preserves Unicode.
    # TOML also forbids DEL (which JSON leaves unescaped).
    return json.dumps(value, ensure_ascii=False).replace("\x7f", "\\u007f")


def yaml_string(value: str) -> str:
    """JSON strings are valid YAML double-quoted scalars, including escapes."""
    return json.dumps(value, ensure_ascii=True)


def render(policy: dict[str, Any], agents: list[Agent], harness: str) -> dict[Path, str]:
    files: dict[Path, str] = {}
    for agent in agents:
        if harness in ("all", "codex"):
            settings = policy["agents"][agent.name]["codex"]
            codex = "\n".join((
                f"name = {toml_string(agent.name)}",
                f"description = {toml_string(agent.description)}",
                f"model = {toml_string(settings['model'])}",
                f"model_reasoning_effort = {toml_string(settings['effort'])}",
                f"developer_instructions = {toml_string(agent.prompt)}",
                "",
            ))
            files[GENERATED / "codex/agents" / f"{agent.name}.toml"] = codex
        if harness in ("all", "claude"):
            settings = policy["agents"][agent.name]["claude"]
            claude = [
                "---", f"name: {agent.name}", f"description: {yaml_string(agent.description)}",
                f"tools: {', '.join(CAPABILITY_TOOLS['claude'][tool] for tool in agent.tools)}",
                f"model: {yaml_string(settings['model'])}",
                f"effort: {yaml_string(settings['effort'])}",
            ]
            claude.extend(["---", "", agent.prompt.rstrip(), ""])
            files[GENERATED / "claude/agents" / f"{agent.name}.md"] = "\n".join(claude)
        if harness in ("all", "pi"):
            settings = policy["agents"][agent.name]["pi"]
            pi = [
                "---", f"name: {agent.name}", f"description: {yaml_string(agent.description)}",
                f"tools: {', '.join(CAPABILITY_TOOLS['pi'][tool] for tool in agent.tools)}",
                f"model: {yaml_string(settings['model'])}",
                f"thinking: {yaml_string(settings['effort'])}",
            ]
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
    selected_harnesses = [selected for selected in HARNESSES if harness in ("all", selected)]
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
        if "agents" in components:
            destination_root = codex_home() / "agents"
            for agent in agents:
                agent_file = GENERATED / "codex/agents" / f"{agent.name}.toml"
                links.append(Link(destination_root / agent_file.name, agent_file))
    if harness in ("all", "claude"):
        if "agents" in components:
            for agent in agents:
                agent_file = GENERATED / "claude/agents" / f"{agent.name}.md"
                links.append(Link(user_home / ".claude/agents" / agent_file.name, agent_file))
        if "skills" in components:
            for skill in sorted((ROOT / "content/skills").iterdir()):
                if skill.is_dir() and (skill / "SKILL.md").is_file():
                    links.append(Link(user_home / ".claude/skills" / skill.name, skill))
        if "statusline" in components:
            links.append(Link(user_home / ".claude/statusline.sh", CLAUDE_STATUSLINE))
    if harness in ("all", "pi", "codex"):
        # Pi and Codex intentionally consume the same user-level skill links.
        if "skills" in components:
            links.extend(shared_skill_links(user_home))
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


def instruction_destinations(harness: str) -> list[Path]:
    user_home = home()
    destinations: list[Path] = []
    if harness in ("all", "codex"):
        destinations.append(codex_home() / "AGENTS.md")
    if harness in ("all", "claude"):
        destinations.append(user_home / ".claude/CLAUDE.md")
    if harness in ("all", "pi"):
        destinations.extend((user_home / ".agents/AGENTS.md", user_home / ".pi/agent/AGENTS.md"))
    return list(dict.fromkeys(destinations))


def read_instruction_destination(path: Path) -> InstructionSnapshot | None:
    try:
        status = path.lstat()
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(status.st_mode):
        content = os.readlink(path)
        return InstructionSnapshot(status.st_dev, status.st_ino, status.st_mode, content)
    if not stat.S_ISREG(status.st_mode):
        raise KitError("not a regular instruction file")
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as stream:
        opened = os.fstat(stream.fileno())
        if not stat.S_ISREG(opened.st_mode) or not os.path.samestat(status, opened):
            raise KitError("instruction destination changed while reading")
        return InstructionSnapshot(opened.st_dev, opened.st_ino, opened.st_mode, stream.read())


def merge_instruction_section(current: bytes, section: bytes) -> tuple[str, bytes]:
    markers = list(INSTRUCTION_MARKERS.finditer(current))
    if not markers:
        separator = b""
        if current:
            separator = b"\n" if current.endswith(b"\n") else b"\n\n"
        return "insert", current + separator + section
    if [marker[1] for marker in markers] != [INSTRUCTIONS_START, INSTRUCTIONS_END]:
        raise KitError("malformed or duplicate instruction section markers")
    updated = current[:markers[0].start()] + section + current[markers[1].end():]
    return ("noop" if updated == current else "refresh"), updated


def instruction_operations(harness: str) -> list[Operation]:
    try:
        source = COMMON_INSTRUCTIONS.read_bytes()
    except OSError as error:
        raise KitError(f"could not read common instructions: {error}") from error
    if INSTRUCTION_MARKERS.search(source):
        raise KitError(f"common instructions contain reserved section markers: {COMMON_INSTRUCTIONS}")
    body = source if source.endswith(b"\n") else source + b"\n"
    section = INSTRUCTIONS_START + b"\n" + body + INSTRUCTIONS_END + b"\n"
    canonical = COMMON_INSTRUCTIONS.resolve()
    operations: list[Operation] = []
    for path in instruction_destinations(harness):
        validate_managed_ancestors(path)
        try:
            content = section
            if path == canonical:
                raise KitError("destination is the canonical instructions source")
            original = read_instruction_destination(path)
            if original is None:
                action = "create"
            elif isinstance(original.content, str):
                if path.resolve(strict=True) != canonical:
                    raise KitError("foreign symlink")
                action = "migrate"
            else:
                action, content = merge_instruction_section(original.content, section)
            operations.append(Operation(action, instruction=InstructionWrite(path, content, original)))
        except (RuntimeError, OSError) as error:
            operations.append(Operation("conflict", f"{path}: {error}"))
    return operations


def write_instruction_file(write: InstructionWrite) -> None:
    path = write.destination
    validate_managed_ancestors(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        validate_managed_ancestors(path)
        if write.original is None:
            with path.open("xb") as stream:
                stream.write(write.content)
            return
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(write.content)
                if stat.S_ISREG(write.original.mode):
                    os.fchmod(stream.fileno(), stat.S_IMODE(write.original.mode))
            validate_managed_ancestors(path)
            try:
                unchanged = read_instruction_destination(path) == write.original
                if unchanged and stat.S_ISLNK(write.original.mode):
                    unchanged = path.resolve(strict=True) == COMMON_INSTRUCTIONS.resolve()
            except (RuntimeError, OSError):
                unchanged = False
            if not unchanged:
                raise KitError(f"refusing to replace substituted destination: {path}")
            temporary.replace(path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    except FileExistsError as error:
        raise KitError(f"refusing to replace substituted destination: {path}") from error
    except OSError as error:
        raise KitError(f"could not write instructions at {path}: {error}") from error


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


def pi_settings_path() -> Path:
    value = os.environ.get("PI_CODING_AGENT_DIR")
    if not value:
        return home() / ".pi/agent/settings.json"
    directory = Path(value)
    if value == "~" or value.startswith("~/"):
        directory = home() / Path(value).relative_to("~")
    if not directory.is_absolute() or ".." in directory.parts:
        raise KitError("PI_CODING_AGENT_DIR must be an absolute or home-relative path without '..' components")
    return directory / "settings.json"


def pi_package_operations(components: frozenset[str]) -> tuple[list[Operation], list[Operation]]:
    settings_path = pi_settings_path()
    packages = read_pi_settings(settings_path).get("packages", [])
    if not isinstance(packages, list):
        raise KitError(f"Pi settings packages must be a list: {settings_path}")
    sources = [entry.get("source") if isinstance(entry, dict) else entry for entry in packages]
    sources = [source.strip() for source in sources if isinstance(source, str) and source.strip()]
    content = []
    if "agents" in components:
        # Pi can store local paths relative to its settings directory.
        paths = (settings_path.parent / (home() / source[2:] if source.startswith("~/") else source) for source in sources)
        registered = any(Path(os.path.abspath(path)) == ROOT for path in paths)
        content.append(Operation("noop" if registered else "pi install", "Pi agent package", source=str(ROOT)))
    extensions = []
    if "extensions" in components:
        npm_specs = [source.removeprefix("npm:").strip() for source in sources if source.startswith("npm:")]
        for package in PI_EXTENSIONS:
            # Compare npm package identity, ignoring version or tag, including for scoped packages.
            name = package.removeprefix("npm:")
            registered = any(spec == name or spec.startswith(name + "@") for spec in npm_specs)
            extensions.append(Operation("noop" if registered else "pi install", "Pi extension", source=package))
    return content, extensions


def statusline_hints(harness: str, components: frozenset[str]) -> list[str]:
    """Explain why Claude is not using the status line; empty when it is.

    Claude's settings are only ever read here, so a symlink is followed and an
    unreadable file degrades to "not configured" instead of aborting.
    """
    if harness not in ("all", "claude") or "statusline" not in components:
        return []
    user_home = home()
    path = user_home / ".claude/settings.json"
    hints: list[str] = []
    settings: Any = {}
    try:
        settings = json.loads(path.read_text())
    except FileNotFoundError:
        pass
    except (OSError, ValueError, RecursionError) as error:
        hints.append(f"warning: cannot read Claude settings {path}: {error}")
    if not isinstance(settings, dict):
        hints.append(f"warning: Claude settings do not contain a JSON object: {path}")
        settings = {}
    statusline = settings.get("statusLine")
    accepted = {STATUSLINE_COMMAND, os.path.expanduser(STATUSLINE_COMMAND), str(user_home / ".claude/statusline.sh")}
    command = statusline.get("command") if isinstance(statusline, dict) else None
    if isinstance(statusline, dict) and statusline.get("type") == "command" and isinstance(command, str) and command in accepted:
        return []
    return [*hints, STATUSLINE_HINT]


def install_plan(harness: str, agents: list[Agent], components: frozenset[str]) -> list[Operation]:
    """The ordered install plan: content first, then third-party extensions."""
    pi_content, pi_extensions = [], []
    if harness in ("all", "pi") and components.intersection(("agents", "extensions")):
        pi_content, pi_extensions = pi_package_operations(components)
    operations: list[Operation] = []
    if "agents" in components:
        generated_paths = [GENERATED / selected / "agents" for selected in HARNESSES if harness in ("all", selected)]
        operations.append(Operation("render", f"generate selected agent trees at {', '.join(map(str, generated_paths))}"))
    operations.extend(pi_content)
    if "instructions" in components:
        operations.extend(instruction_operations(harness))
    operations.extend(link_operations(harness, agents, components))
    operations.extend(pi_extensions)
    return operations


def print_plan(operations: list[Operation]) -> None:
    for operation in operations:
        suffix = f" ({operation.detail})" if operation.detail else ""
        action = f"[{operation.action.upper()}]"
        if operation.link is not None:
            print(f"{action:12} {operation.link.destination} -> {operation.link.target}{suffix}")
        elif operation.instruction is not None:
            print(f"{action:12} {operation.instruction.destination}{suffix}")
        elif operation.source is not None:
            print(f"{action:12} {operation.source}{suffix}")
        else:
            print(f"{action:12} {operation.detail}")


def validate_generated_trees(harness: str) -> None:
    """Reject selected generated trees that could redirect reads or writes."""
    for selected in HARNESSES:
        if harness in ("all", selected):
            validate_generated_destination(GENERATED / selected / "agents")


def verify_generated(files: dict[Path, str], harness: str) -> bool:
    validate_generated_trees(harness)
    if not all(path.is_file() and not path.is_symlink() and path.read_text() == content for path, content in files.items()):
        return False
    for selected in HARNESSES:
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
    for hint in statusline_hints(harness, components):
        print(hint)
    if any(operation.action == "conflict" for operation in operations):
        raise KitError("refusing to overwrite unmanaged destinations")
    extension_failures: list[str] = []
    for operation in operations:
        if operation.action == "render":
            materialize(files, harness)
        elif operation.action == "pi install":
            assert operation.source is not None
            read_pi_settings(pi_settings_path())
            try:
                run(["pi", "install", operation.source])
            except KitError as error:
                if operation.source not in PI_EXTENSIONS:
                    raise
                extension_failures.append(str(error))
        elif operation.instruction is not None and operation.action != "noop":
            write_instruction_file(operation.instruction)
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
    if extension_failures:
        raise KitError("Pi extension installation failed after content operations:\n" + "\n".join(extension_failures))
    return 0


def check(harness: str, components: frozenset[str]) -> int:
    policy, agents = load_catalog(harness, components)
    files = render(policy, agents, harness) if agents else {}
    operations = [operation for operation in install_plan(harness, agents, components) if operation.action != "render"]
    drift = ("agents" in components and not verify_generated(files, harness)) or any(operation.action != "noop" for operation in operations)
    hints = statusline_hints(harness, components)
    drift = drift or bool(hints)
    if drift:
        print("harness-kit is valid but not converged; run: uv run harness-kit install")
        print_plan(operations)
        for hint in hints:
            print(hint)
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
        item.add_argument("--harness", choices=("all", *HARNESSES), default="all", help="limit to this harness (default: all)")
        item.add_argument("--component", action="append", choices=COMPONENT_CHOICES, help="deploy only this component (repeatable)")
    args = parser.parse_args(argv)
    try:
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
            for hint in statusline_hints(args.harness, components):
                print(hint)
            return 2 if any(operation.action == "conflict" for operation in operations) else 0
        if args.command == "install":
            return install(args.harness, components)
        return check(args.harness, components)
    except KitError as error:
        print(f"harness-kit: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
