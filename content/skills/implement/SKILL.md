---
name: implement
description: "Implement a piece of work based on a spec or set of tickets."
disable-model-invocation: true
---

Implement the work described by the user in the spec or tickets.

If the user passes a ticket reference, fetch it with its comments using the "fetch the relevant ticket" workflow in `docs/agents/issue-tracker.md`, then read its parent spec and any blocking tickets. If a blocker is still open, stop and tell the user which one instead of starting.

Unless the user explicitly specifies otherwise, all implementation, documentation, testing, and other repository work must be done in a separate git worktree created from `main`. Fetch the remote first and branch from its `main` (e.g. `origin/main`), not a possibly stale local `main`, on a branch named after the ticket (e.g. `<number>-<short-slug>`), in the repo's usual worktree location. Do not make task changes directly in the primary checkout.

Load the `tdd` skill (on Claude Code, call the Skill tool with "tdd"; elsewhere, read its `SKILL.md`) and use it where possible, at pre-agreed seams. Before confirming seams, check each new type, view or factory the ticket names against the existing code, and propose reusing any existing artifact that already holds that data or behavior. Confirm the seams with the user before writing the first test; seams the ticket or spec names explicitly count as agreed, except a ticket-named new type this check replaced.

When the spec and the existing code disagree, or the spec is silent on a decision the code sets no precedent for, stop and put the options to the user with your recommendation.

Keep changes to what the ticket asks. Collect anything you spot outside it in a **Noticed, not touched** list for the final message.

Build and run the relevant single tests regularly as you go. Commit each slice as a **save point** once it's green - the build passes and the tests covering it pass - staging only that slice's files, so every commit on the branch is a working state. When a slice won't go green, `git restore` back to the last save point and rethink it rather than committing it broken. Run the full test suite once all slices are in.

Once the suite is green, load the `code-simplification` skill (on Claude Code, call the Skill tool with "code-simplification"; elsewhere, read its `SKILL.md`) and use it on the work, passing the remote `main` the worktree branched from (e.g. `origin/main`) as the fixed point. Merge its out-of-scope notes into **Noticed, not touched**.

Once done, load the `code-review` skill (on Claude Code, call the Skill tool with "code-review"; elsewhere, read its `SKILL.md`) and use it to review the work, passing the same fixed point.

Commit each review fix as its own save point, then push the branch, load the `pr` skill (on Claude Code, call the Skill tool with "pr"; elsewhere, read its `SKILL.md`) to shape the PR body, include the ticket's closing keyword where the tracker supports one (e.g. `Closes #N`), and open the PR. Skip or adjust this step if the user says otherwise (e.g. no PR wanted).

End with the **Noticed, not touched** list (if any), then a brief FYI: `/cleanup-merged-worktree` is available once the PR merges, and `/retro` if the session felt bumpy.
