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

## Work Queue

- Treat all work as a FIFO queue of todos, and finish the item in hand before starting the next.
- When I propose a tweak, change, or correction mid-task, append it to the back of the queue and carry on with the current item.
- Stop only when every item in the queue is complete and verified.

## Mistakes

- Treat every mistake as evidence of a gap in the instruction files (`AGENTS.md`, `CLAUDE.md`, skills), so skip the apology.
- Name the instruction gap that caused it and propose the concrete edit that closes it.

## Scope

- Apply YAGNI: build the minimum the task requires, and justify every change by the task it serves.
- Expand scope only with my permission; offer scope improvements as suggestions when they make sense.
- Gauge where the project sits between quick-and-dirty and production-grade, and match engineering rigor to that point.
