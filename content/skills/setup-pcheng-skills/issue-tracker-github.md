# Issue tracker: GitHub

Specs and tickets for this repo live as GitHub issues. Use the `gh` CLI for all operations.

## Conventions

- **Create an issue**: `gh issue create --title "..." --body "..."`. Use a heredoc for multi-line bodies.
- **Read an issue**: `gh issue view <number> --json number,title,body,labels,comments`. Off a TTY, `gh issue view --comments` prints only the comments, not the body.
- **List issues**: `gh issue list --state open --json number,title,body,labels,comments --jq '[.[] | {number, title, body, labels: [.labels[].name], comments: [.comments[].body]}]'` with appropriate `--label` and `--state` filters.
- **Comment on an issue**: `gh issue comment <number> --body "..."`
- **Apply / remove labels**: `gh issue edit <number> --add-label "..."` / `--remove-label "..."`
- **Close**: post the explanation with `gh issue comment <number> --body "..."`, then `gh issue close <number>`. On an already-closed issue, `gh issue close --comment` drops the comment and still exits 0.
- **Blocking links**: `gh issue create ... --blocked-by <n>,<n>` sets native "blocked by" links at creation; `gh issue edit <number> --add-blocked-by <n>` / `--remove-blocked-by <n>` change them later. Both take issue numbers, so no `gh api` call or issue ID lookup is needed. A ticket is unblocked when every blocker is closed.
- **Count open blockers**: `gh api repos/{owner}/{repo}/issues/<number> --jq .issue_dependencies_summary.blocked_by` (open blockers only; 0 means startable). To name them: `gh issue view <number> --json blockedBy --jq '[.blockedBy.nodes[] | select(.state == "OPEN") | .number]'`. Unfiltered, `blockedBy` also lists closed blockers.
- **Make an issue a sub-issue of a parent**: `gh issue create --parent <parent> ...`, or `gh issue edit <parent> --add-sub-issue <child>` afterwards. Without sub-issues, put `Part of #<parent>` at the top of the child body.

Infer the repo from `git remote -v` - `gh` does this automatically when run inside a clone.

File issues only into the user's own repo. In a fork, `gh` can default to the upstream parent, so before the first `gh issue create` of a session, check the target with `gh repo view --json nameWithOwner` and confirm it with the user if it is not their repo.

## Pull requests as a triage surface

**PRs as a request surface: no.** _(Set to `yes` if this repo treats external PRs as feature requests; `/triage` reads this flag.)_

When set to `yes`, PRs run through the same labels and states as issues, using the `gh pr` equivalents:

- **Read a PR**: `gh pr view <number>`, then `gh pr view <number> --comments` (off a TTY, `--comments` prints only the comments, not the body), and `gh pr diff <number>` for the diff.
- **List external PRs for triage**: `gh api --paginate 'repos/{owner}/{repo}/pulls?state=open' --jq '.[] | select(.author_association | IN("OWNER","MEMBER","COLLABORATOR") | not) | {number, title, author: .user.login, author_association, labels: [.labels[].name]}'`.
- **Comment / label / close**: `gh pr comment`, `gh pr edit --add-label`/`--remove-label`, `gh pr close`.

GitHub shares one number space across issues and PRs, so a bare `#42` may be either - resolve with `gh pr view 42` and fall back to `gh issue view 42`.

## When a skill says "publish to the issue tracker"

Create a GitHub issue.

## When a skill says "fetch the relevant ticket"

Read it as in **Read an issue** above.

An agent brief comment (from the `triage` skill) is the contract: where it and the issue body disagree, the newest brief wins.
