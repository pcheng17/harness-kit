---
name: implement-spec
description: "Implement the result of /to-spec and /to-tickets in code, running tickets in parallel."
disable-model-invocation: true
---

You have been provided a spec. This spec should have tickets associated with it, describing how to implement the spec.

The issue tracker should have been provided to you. If not, tell the user to run `/setup-pcheng-skills`. Its "Wayfinding operations" section says how to read a ticket's blockers and find the frontier.

The goal is the entire spec implemented on a single **integration branch**, with every ticket resolved the way the issue tracker closes work. Never commit to `main`.

The tickets are not a list of steps. They are a **task graph** with blocking relationships between them. This means there is always a **frontier** of tickets which are ready to be grabbed: tickets not yet done whose blockers are all done. A ticket counts as done once it is closed in the tracker or its branch has landed on the integration branch during this run.

Communication to and from sub-agents should be sparse. Communicate primarily through **context pointers**: to the spec, tickets, research notes, and previous commits. Don't duplicate information already available via pointers.

## Roles

Spawn each role as a sub-agent using this repo's named agents. Their standing prompts don't know about this workflow, so the instructions listed for each role go in the prompt you send it.

- **Implementer**: the `builder` agent, one per ticket, run in the background where the harness allows for maximum concurrency. Its prompt carries the ticket pointer, the spec pointer, any notes pointer, its worktree path, its branch, the integration branch, and these instructions:
  - work only in the given worktree;
  - confirm the worktree is based on the integration branch before starting (`git merge-base --is-ancestor <integration> HEAD`), and if not, reset onto it (`git reset --hard <integration>`) before making any changes;
  - load the `tdd` skill (on Claude Code, call the Skill tool with "tdd"; elsewhere, read its `SKILL.md`) and use it to build the ticket;
  - commit on its own branch, then merge the integration branch tip into it (`git merge --no-edit <integration>`), resolve any conflicts, and rerun the tests before reporting done, so landing it is a fast-forward.
- **Verifier**: the `refuter` agent. Its prompt carries the ticket pointer, the worktree path, and the diff to check (`git diff <integration>...<ticket-branch>`). It reruns the tests in that worktree and reports findings; it does not fix.
- **Explorer** (optional): the `scout` agent. It locates files, symbols and call sites and reports paths; it cannot write files, so you save its findings as notes.

## Steps

1. Read the spec and tickets to understand the task graph: each ticket's blockers, read the way the tracker's "Wayfinding operations" describe.

2. (optional) Spawn an explorer to locate what the tickets touch in the codebase. Save its findings as markdown notes in a directory outside the repo, accessible by all future sub-agents, and pass that path to implementers as a context pointer. This lets implementers focus on implementation rather than exploration.

3. Create the integration branch from `main` in its own worktree, so the primary checkout is untouched: `git worktree add -b <integration> <integration-path> main`. Put worktrees wherever this repo keeps them; if unsure, use a sibling directory of the checkout. If the issue tracker closes work through PRs, or the user asks for one, push the integration branch and open a draft PR after the first landing in step 5 (a branch with no commits ahead of `main` can't open one), marked as closing the spec and tickets. Push again after each later landing.

4. For each ticket on the frontier, create its worktree on its own branch from the integration tip: `git worktree add -b <integration>-<ticket> <ticket-path> <integration>`. Mark the ticket started if the tracker records that (for example, In Progress on Linear, `in-progress` locally). Spawn an implementer for it.

5. Once an implementer completes, spawn a verifier on its branch. If the verifier finds problems, send them back to an implementer in the same worktree and verify again. Once verified, land it from the integration worktree: `git -C <integration-path> merge --ff-only <integration>-<ticket>`. If the fast-forward fails because another ticket landed first, have an implementer merge the new integration tip into the ticket branch and rerun the tests, then verify and land again.

6. Recompute the **frontier** after each landing. If it has new tickets, go back to step 4 for them while other implementers are still running. This allows for maximum concurrency. Continue until every ticket has landed.

7. Once all tickets have landed, from the integration worktree, load the `code-review` skill (on Claude Code, call the Skill tool with "code-review"; elsewhere, read its `SKILL.md`) and review the integration branch against `main`. Fix all issues raised by the review in a single implementer, in a fresh worktree from the integration tip, then verify and land it as in step 5.

8. If a draft PR exists, push the integration branch and mark the PR ready for review. Otherwise, resolve each ticket the way the issue tracker closes work, and report the integration branch.

9. Clean up every implementer worktree: `git worktree remove <ticket-path>` for each, then delete its branch from the integration worktree, `git -C <integration-path> branch -d <integration>-<ticket>` (`-d` checks the branch is merged into the current `HEAD`, which there is the integration branch). Remove the integration worktree last (`git worktree remove <integration-path>`); the integration branch stays. Run `git worktree prune` and confirm with `git worktree list` that none of this run's worktrees remain.
