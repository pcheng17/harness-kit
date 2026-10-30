# Global Agent Instructions

- Never use em dashes. Always use hyphens instead.

## Subagent Preference

- Prefer using subagents whenever a task can be meaningfully delegated.
- For every non-trivial task, use at least one subagent unless delegation would clearly add no value.
- Parallelize independent investigation, implementation, and review work when practical.
- Use separate read-only reviewer subagents for important or risky changes.
- Keep the parent agent responsible for coordination, synthesis, final verification, and communicating results.
- Do not delegate trivial tasks where the overhead would outweigh the benefit.

## Worktrees

- Do all repository work in a linked worktree, never the primary checkout.
- Take one with the `worktree-slots` skill: `~/.claude/skills/worktree-slots/scripts/wt.sh take <branch>` (`~/.agents/skills/worktree-slots/scripts/wt.sh` on Pi and Codex), then `cd` to the path printed on the last line.
- Park it with `wt.sh park` as soon as its PR is opened (everything committed and pushed) or the work is abandoned. Do not leave parking to the user; to work on the branch again, take a fresh slot.
- When a repo's `AGENTS.md` prescribes a different worktree recipe, follow the repo.
