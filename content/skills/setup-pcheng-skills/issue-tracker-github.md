# Issue tracker: GitHub

Specs and tickets for this repo live as GitHub issues. Use the `gh` CLI for all operations.

## Conventions

- **Create an issue**: `gh issue create --title "..." --body "..."`. Use a heredoc for multi-line bodies.
- **Read an issue**: `gh issue view <number> --comments`, filtering comments by `jq` and also fetching labels.
- **List issues**: `gh issue list --state open --json number,title,body,labels,comments --jq '[.[] | {number, title, body, labels: [.labels[].name], comments: [.comments[].body]}]'` with appropriate `--label` and `--state` filters.
- **Comment on an issue**: `gh issue comment <number> --body "..."`
- **Apply / remove labels**: `gh issue edit <number> --add-label "..."` / `--remove-label "..."`
- **Close**: `gh issue close <number> --comment "..."`
- **Blocking links**: `gh issue create ... --blocked-by <n>,<n>` sets native "blocked by" links at creation; `gh issue edit <number> --add-blocked-by <n>` / `--remove-blocked-by <n>` change them later. Both take issue numbers, so no `gh api` call or issue ID lookup is needed. Sub-issues use `--parent <n>` (create) or `--add-sub-issue <n>` (edit).
- **Read blocking links**: `gh api repos/{owner}/{repo}/issues/<number>/dependencies/blocked_by --jq '[.[].number]'`

Infer the repo from `git remote -v` - `gh` does this automatically when run inside a clone.

## Wayfinding operations

Used by `/implement-spec` to read a spec's tickets as a task graph.

- **Express a blocking link**: use the native "blocked by" links from Conventions above (`--blocked-by` on create, `--add-blocked-by` on edit). Where dependencies aren't available on the repo, fall back to a `Blocked by: #<n>, #<n>` line in the ticket body.
- **Read a ticket's blockers**: `gh issue view <number> --json blockedBy --jq '[.blockedBy.nodes[] | {number, state}]'`, or the `gh api` call under Conventions (each entry carries `number` and `state`). For the fallback, parse the `Blocked by` line and check each issue's state.
- **The spec's tickets**: the spec issue's sub-issues (`gh issue view <spec> --json subIssues --jq '[.subIssues.nodes[].number]'`) when to-tickets used them; otherwise the tickets the spec or the user lists.
- **Frontier**: the open tickets whose blockers are all closed. One call lists them with their blockers: `gh issue list --state open --json number,title,blockedBy --jq '[.[] | select(all(.blockedBy.nodes[]; .state == "CLOSED")) | .number]'`, then keep only the spec's tickets. A ticket is unblocked when every blocker is closed.
- **Resolve**: close the ticket (`gh issue close <number> --comment "..."`), or let a merged PR that says `Closes #<number>` close it.

## Pull requests as a triage surface

**PRs as a request surface: no.** _(Set to `yes` if this repo treats external PRs as feature requests; `/triage` reads this flag.)_

When set to `yes`, PRs run through the same labels and states as issues, using the `gh pr` equivalents:

- **Read a PR**: `gh pr view <number> --comments` and `gh pr diff <number>` for the diff.
- **List external PRs for triage**: `gh pr list --state open --json number,title,body,labels,author,authorAssociation,comments` then keep only `authorAssociation` of `CONTRIBUTOR`, `FIRST_TIME_CONTRIBUTOR`, or `NONE` (drop `OWNER`/`MEMBER`/`COLLABORATOR`).
- **Comment / label / close**: `gh pr comment`, `gh pr edit --add-label`/`--remove-label`, `gh pr close`.

GitHub shares one number space across issues and PRs, so a bare `#42` may be either - resolve with `gh pr view 42` and fall back to `gh issue view 42`.

## When a skill says "publish to the issue tracker"

Create a GitHub issue.

## When a skill says "fetch the relevant ticket"

Run `gh issue view <number> --comments`.
