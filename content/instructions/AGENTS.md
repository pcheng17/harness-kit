# Global Agent Instructions

## Tone and style

- Never use the word "honest" in phrases like "here's my honest review" or "here's honest feedback" - it adds no meaning and reads as filler.
- Never use em dashes. Always use hyphens instead.

## Subagent Preference

- Prefer using subagents whenever a task can be meaningfully delegated.
- For every non-trivial task, use at least one subagent unless delegation would clearly add no value.
- Parallelize independent investigation, implementation, and review work when practical.
- Use separate read-only reviewer subagents for important or risky changes.
- Keep the parent agent responsible for coordination, synthesis, final verification, and communicating results.
- Do not delegate trivial tasks where the overhead would outweigh the benefit.

## Software development guidelines

- Always create a new branch and worktree for new changes.
- The `main` branch should always remain free of changes.
- Never commit nor push to the `main` branch.
