# Issue tracker: Local Markdown

Specs and tickets for this repo live as markdown files in `.scratch/`.

## Conventions

- One feature per directory: `.scratch/<feature-slug>/`
- The spec is `.scratch/<feature-slug>/spec.md`
- Each ticket is its own file at `.scratch/<feature-slug>/issues/<NN>-<slug>.md`, numbered from `01` (never a single combined tickets file)
- Triage state is recorded as a `Status:` line near the top of each ticket file (see `triage-labels.md` for the role strings)
- Comments and conversation history append to the bottom of the file under a `## Comments` heading

## Wayfinding operations

Used by `/implement-spec` to read a spec's tickets as a task graph. The tickets are the files in `.scratch/<feature-slug>/issues/`, written from the to-tickets local template.

- **Express a blocking link**: the ticket file's `**Blocked by:**` line lists the numbers of the tickets that gate it (`**Blocked by:** 01, 02`), or `None - can start immediately`.
- **Read a ticket's blockers**: read that line and open each listed `issues/<NN>-*.md` file.
- **Status marker**: the `**Status:**` line. It starts as a triage role (`ready-for-agent`); set it to `in-progress` while an implementer is working the ticket and to `done` once its work has landed.
- **Frontier**: the ticket files whose status is neither `done` nor `in-progress` and whose every blocker has `**Status:** done`. Lowest number first when you have to pick.
- **Resolve**: set `**Status:** done` and append a context pointer (commit or branch) under the file's `## Comments` heading.

## When a skill says "publish to the issue tracker"

Create a new file under `.scratch/<feature-slug>/` (creating the directory if needed).

## When a skill says "fetch the relevant ticket"

Read the file at the referenced path. The user will normally pass the path or the ticket number directly.
