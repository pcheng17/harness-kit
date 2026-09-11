# Issue tracker: Linear

Issues and PRDs for this repo live as Linear issues.

## MCP only — no CLI

Unlike GitHub/GitLab, there is no local CLI for Linear. All operations go through the **Linear MCP server** (`mcp__linear__*` tools). Before first use in a session:

1. Check whether Linear's real tools (create/read/list/comment) are already available via `ToolSearch`. If only `mcp__linear__authenticate` / `mcp__linear__complete_authentication` show up, the server isn't authenticated yet.
2. If not authenticated, call `mcp__linear__authenticate` to start the OAuth flow, share the authorization URL with the user, then call `mcp__linear__complete_authentication` with the callback URL once they approve it in their browser.
3. Once authenticated, the server's real tools (issue create/read/list/comment/update, team and project lookups, etc.) become available. Use `ToolSearch` to find their exact names and schemas — they're versioned by the MCP server and shouldn't be hard-coded here.

Re-check authentication at the start of any session that needs Linear — it does not persist across all environments (e.g. remote/headless runs may lose it).

## Team scoping

Linear issues live under a specific **team** (and optionally a **project**) within the workspace, not just "the repo." `/setup-pcheng-skills` resolves this once, at setup time, and records it below — skills should read it from here rather than asking the user each time.

**Team:** _(filled in by `/setup-pcheng-skills`)_
**Project:** _(optional — filled in by `/setup-pcheng-skills` if the user scopes to one)_

## Conventions

- **Identifiers**: Linear issues are addressed by a team-prefixed key like `ENG-123`, not a bare number. Use the full key when referencing an issue.
- **Create an issue**: use the MCP create-issue tool, passing the team (and project, if applicable), title, and description.
- **Read an issue**: use the MCP get/read-issue tool with its `ENG-123`-style identifier.
- **List issues**: use the MCP list/search-issues tool, filtered by team, state, and/or label as needed.
- **Comment on an issue**: use the MCP create-comment tool.
- **Labels vs. state**: Linear separates **workflow state** (e.g. Backlog, Todo, In Progress, Done, Canceled — one per issue) from **labels** (free-form tags, many per issue). Triage roles map to **labels** here (see `triage-labels.md`), independent of whatever workflow state the issue is in.
- **Starting work**: when beginning work on a Linear ticket, transition its state to **In Progress** via the MCP update-issue tool.
- **Triage label removal**: whenever a ticket's state is transitioned to In Progress, remove its triage label (see `triage-labels.md`) as part of that same update, if one is present on the ticket.
- **Opening a PR**: include the Linear ticket's URL and key in the PR description, so GitHub and Linear can connect the PR to the ticket.
- **Close**: setting an issue's state to a terminal state (e.g. Done/Canceled) via the MCP update-issue tool — there is no separate "close" action.

## Pull/merge requests as a triage surface

Not applicable. Linear is issue-only — it doesn't host code or pull requests. If this repo's PRs/MRs live on GitHub or GitLab, configure that surface separately in `docs/agents/issue-tracker.md` (Linear can still be the source of truth for issues while PRs are triaged on the git host).

## When a skill says "publish to the issue tracker"

Create a Linear issue via the MCP create-issue tool, in the configured team/project.

## When a skill says "fetch the relevant ticket"

Use the MCP get-issue tool with the issue's `ENG-123`-style identifier.
