---
name: implement
description: "Implement a piece of work based on a spec or set of tickets."
disable-model-invocation: true
---

Implement the work described by your caller in the spec or tickets. Your **caller** is whoever gave you this work: the user, or the agent that briefed you. If you can't ask them mid-task, end your turn with the question.

If your caller passes a ticket reference, fetch it with its comments using the "fetch the relevant ticket" workflow in `docs/agents/issue-tracker.md`, then read its parent spec and any blocking tickets. If a blocker is still open, stop and tell your caller which one instead of starting.

Do all work in a separate worktree on a branch named after the ticket (e.g. `<number>-<short-slug>`). Unless the repo prescribes its own recipe, load the `worktree-slots` skill (on Claude Code, call the Skill tool with "worktree-slots"; elsewhere, read its `SKILL.md`), take the worktree with its `scripts/wt.sh take <branch>` and `cd` to the path it prints last; otherwise branch from a freshly fetched `origin/main`.

Before writing code, read the coding standards the reviewer will hold the work to: the standards sources and smell baseline in step 3 of the `code-review` skill (`../code-review/SKILL.md`, relative to this skill's folder). Read that step only; review runs later. Write to those standards from the first slice.

Load the `tdd` skill (on Claude Code, call the Skill tool with "tdd"; elsewhere, read its `SKILL.md`) and use it where possible, at pre-agreed seams. Before confirming seams, check each new type, view or factory the ticket names against the existing code, and propose reusing any existing artifact that already holds that data or behavior. Confirm the seams with your caller before writing the first test; seams the ticket or spec names explicitly count as agreed, except a ticket-named new type this check replaced.

When the spec and the existing code disagree, or the spec is silent on a decision the code sets no precedent for, stop and put the options to your caller with your recommendation.

Keep changes to what the ticket asks. Collect anything you spot outside it in a **Noticed, not touched** list for the final message.

Build and run the relevant single tests regularly as you go. Commit each slice as a **save point** once it's green - the build passes and the tests covering it pass - and tidied by `tdd`'s refactor step, staging only that slice's files, so every commit on the branch is a working state. When a slice won't go green, `git restore` back to the last save point and rethink it rather than committing it broken. Run the full test suite once all slices are in.

Once the suite is green, load the `code-review` skill (on Claude Code, call the Skill tool with "code-review"; elsewhere, read its `SKILL.md`) and use it to review the work, passing the fixed point (the remote `main` the worktree branched from, e.g. `origin/main`).

Fix the review findings, overbuilt code (Speculative Generality, Middle Man, Lazy Element) included like any other, committing each fix as its own save point. When any fix changes behaviour, give the fix commits' diff to one fresh Correctness reviewer (briefed as in `code-review` step 4) before pushing; fix what it finds and repeat until a pass finds no defect the fixes introduced. Then push the branch, load the `pr` skill (on Claude Code, call the Skill tool with "pr"; elsewhere, read its `SKILL.md`) to shape the PR body, include the ticket's closing keyword where the tracker supports one (e.g. `Closes #N`), open the PR. Skip or adjust this step if your caller says otherwise (e.g. no PR wanted). Park the slot with `wt.sh park` whenever you stop working in it: once the PR is open, or when the work is abandoned or no PR is wanted.

End with the **Noticed, not touched** list (if any), then a brief FYI that you parked the slot (`wt.sh take <branch>` resumes it; `wt.sh prune` reclaims disk), and `/retro` if the session felt bumpy.
