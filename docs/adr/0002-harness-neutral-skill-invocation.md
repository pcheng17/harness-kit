# Invoke other skills with a harness-neutral "Load the skill" instruction

When a skill's own step needs another model-invoked skill, it says: Load the `grilling` skill (on Claude Code, call the Skill tool with "grilling"; elsewhere, read its `SKILL.md`). A step needing two skills says so as two loads: Load the `grilling` and `domain-modeling` skills (on Claude Code, call the Skill tool twice, once for each; elsewhere, read each one's `SKILL.md`). Upstream (mattpocock/skills v1.3.1, #878) standardized on a bare `Call the Skill tool with "x"`, because naming the tool loads the skill more reliably than `/x` prose, but only Claude Code has a tool by that name: Pi lists each skill's name, description, and `SKILL.md` path in the system prompt and tells the model to load it with its `read` tool, and Codex (0.157.0) lists each skill's name, description, and `SKILL.md` path under "Available skills" with no skill tool. So we name the Skill tool for Claude Code and fall back to reading `SKILL.md`, which is how the other two harnesses load skills. A user-invoked skill (`disable-model-invocation: true`) is never loaded this way; a skill that depends on one tells the user to run it, e.g. "tell the user to run `/setup-pcheng-skills`". Sub-agents are requested as "spawn a sub-agent" rather than by a harness's tool name (`Agent`, `spawn_agent`).

## Considered Options

- **Upstream's `Call the Skill tool with "x"` alone**: rejected; Pi and Codex expose no such tool, so the instruction names something the model cannot call there.
- **Bare `/x` or "run the `x` skill"**: rejected; this is the wording upstream found unreliable, and `/x` is Claude Code's syntax (Pi uses `/skill:x`, Codex `$x`).
- **Read `../x/SKILL.md` by relative path**: rejected; it couples skills to the install layout and skips Claude Code's tool-based loading.

## Consequences

- Codex does not honor `disable-model-invocation`: `codex debug prompt-input` lists this repo's user-invoked skills (`setup-pcheng-skills`, `to-spec`, `triage`, ...) among the skills available to the model. On Codex the "never invoke a user-invoked skill" rule is enforced only by skill wording, until skills ship an `agents/openai.yaml` with `policy.allow_implicit_invocation: false`.
