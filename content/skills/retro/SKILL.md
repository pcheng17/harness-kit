---
name: retro
description: "Conduct a retrospective on a coding session."
disable-model-invocation: true
---

The user has asked for a **retrospective**. You are suggesting improvements to the coding agent's **environment** to improve future runs.

## Steps

1. Call the Skill tool with `writing-for-agents` for the writing style guide.

2. Read the primary sources for the session the user specifies. If the user doesn't specify a session, default to the current one. For any other session, read [`SESSION-LOGS.md`](SESSION-LOGS.md) for where each harness stores its transcripts.

3. Look for candidates for improvement in these categories.

- **Navigation**: how easy was it for the agent to find the right files? Are there hidden dependencies between files? Would a **navigation pointer** make it easier? _Use when_ the session took a long time to find a piece of information.
- **Automated checks**: are there automated checks that could catch errors the agent made? Linting, typing, tests, filesystem linters? Read the repo's own check command first (its `package.json`/build-tool `lint`/`check` scripts, its CI workflow), so a check that already exists but sits unwired or silently broken is the finding, not a reinvention. A repo with no **guardrail** (no pre-commit hook and no CI job running its lint/typecheck/test command) is itself a finding: an un-linted repo is a standing missed opportunity, not a neutral default. _Use when_ the agent made a mistake an automated check could have caught, or the repo has no guardrail at all.
- **Coding standards**: should the **reviewer agent** be given a new rule to enforce? Should an existing rule be removed or clarified? Classify the violation first: a **mechanical** one (a fixed syntactic pattern, a banned API, an import shape, a file-location rule) gets a deterministic check, full stop: a custom rule in the repo's own linter, a new pre-commit hook, or a new CI job, whichever the repo's language and existing guardrail make cheapest. Default to building the check over writing the rule. Reserve `CODING_STANDARDS.md` for genuine **judgement calls** (cross-file consistency, "matches the surrounding style," anything no guardrail could ever substitute for). _Use when_ the reviewer agent failed to catch a mistake.
- **Global AGENTS.md**: are there any steering instructions that should be moved to coding standards (or automated checks) instead? _Use when_ the AGENTS.md file is particularly large - in the repo OR the user's global scope. Aim each proposed edit at its **authored source** (see [Steering sources](#steering-sources)).
- **Tool economy**: did the agent make expensive tool calls that could be streamlined? Is there any custom tooling (CLI's, MCP's) that is particularly token-inefficient? _Use when_ the agent made an expensive tool call.
- **No-ops**: look for instructions in steering files that don't modify the agent's behavior. _Use when_ the steering files are large and unwieldy.
- **Information access**: look for opportunities to increase the agent's access to information. Teeing dev server logs, readonly access to third-party services. _Use when_ a crucial piece of information was not available to the agent.

4. Present these candidates to the user, in order of severity. Every candidate names the exact file to edit: an authored source, never a deployed copy.

## Reference

### Implementation vs Review

Remember that all work goes through two stages: implementation and review. The implementation agent has the most **context pressure**. They are responsible for exploration, writing code, and debugging failures.

The review agent has the least context pressure - it receives a diff, so no exploration needed. It often does not need to write code or debug.

This means that the review agent should be responsible for imposing coding standards, not the implementation agent.

### Files

You have access to several files in the repo:

- `CLAUDE.md`/`AGENTS.md`: these files are pushed to the context window of any agent working in this repo. They should be used incredibly sparingly, usually only for **navigation pointers** to other files.
- `CODING_STANDARDS.md`: this file is read during review, not implementation. Add **navigation pointers** to docs folders if the standards file gets more than 1,000 lines long.
- Docs: use docs as references files, pointed to by other files. Look for existing docs before writing new ones.
- Skills: use skills for docs (since their description goes into the agent's context window), or for user-invoked commands. Follow the advice in the `writing-for-agents` skill.

### Steering sources

Global steering and skills are authored once in the harness-kit checkout and deployed to every harness as symlinks. Propose global edits against the **authored source** in that checkout, never a deployed path: a deployed path hides which repo owns the change, and a tool that rewrites the file replaces the link with an unmanaged copy. Find the checkout by resolving a deployed link (`readlink ~/.claude/CLAUDE.md`).

| Finding about | Authored source (in the harness-kit checkout) | Deployed as |
| --- | --- | --- |
| Global steering | `content/instructions/AGENTS.md` | `~/.claude/CLAUDE.md`, `~/.agents/AGENTS.md`, `~/.pi/agent/AGENTS.md`, `$CODEX_HOME/AGENTS.md` |
| A skill | `content/skills/<name>/` | `~/.claude/skills/<name>`, `~/.agents/skills/<name>` |
| An agent definition | `content/agents/<name>/agent.toml` (models in `config.toml`) | rendered into `.generated/`, then linked or registered per harness |

A non-empty `$CODEX_HOME/AGENTS.override.md` replaces the global file for Codex and is user-owned, outside harness-kit; name it as its own target when it is the file in play.

Repo-specific steering (a target repo's own `AGENTS.md`, `CLAUDE.md`, `CODING_STANDARDS.md`, docs) is authored in that repo: propose edits there.
