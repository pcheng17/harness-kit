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

- When you need a worktree (a skill asks for one or I do), take it with the `worktree-slots` skill rather than any built-in worktree tool, and park it with `wt.sh park` when you stop working in it.
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
