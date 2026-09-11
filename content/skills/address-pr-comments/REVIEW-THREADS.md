# Review thread mechanics per platform

Exact commands/tools for fetching review threads (with resolution state) and replying on a specific thread. Use whichever section matches the host resolved in step 0 of [SKILL.md](SKILL.md).

## GitHub

Resolution state (`isResolved`) is only exposed via GraphQL — the REST API doesn't carry it. Fetching and replying therefore use two different APIs.

**Who am I:**
```
gh api user --jq .login
```

**Fetch threads** (repo/PR inferred from `git remote -v`; substitute owner/repo/number):
```
gh api graphql -f query='
  query($owner:String!, $repo:String!, $number:Int!) {
    repository(owner:$owner, name:$repo) {
      pullRequest(number:$number) {
        reviewThreads(first: 100) {
          nodes {
            id
            isResolved
            path
            line
            comments(first: 50) {
              nodes { databaseId author { login } body url createdAt }
            }
          }
        }
      }
    }
  }' -f owner=<owner> -f repo=<repo> -F number=<pr-number>
```
Paginate with `reviewThreads(first:100, after:$cursor)` if a PR has more than 100 threads.

**Reply to a thread** — reply to the *first* comment's `databaseId` in that thread (this is what threads the reply correctly; replying to a later comment in the same thread also works since GitHub threads by the root comment):
```
gh api repos/<owner>/<repo>/pulls/<pr-number>/comments/<databaseId>/replies -f body="Addressed in <commit-link>."
```

**Commit link format:** `https://github.com/<owner>/<repo>/commit/<sha>`

## GitLab

Unlike GitHub, resolution state and reply-in-place are both available through the plain REST API (via `glab api`) — no GraphQL needed.

**Who am I:**
```
glab api user --jq .username
```

**Fetch discussions** (each discussion is a thread; `resolvable`/`resolved` are per-note but consistent within a discussion):
```
glab api projects/:id/merge_requests/<mr-iid>/discussions
```
`:id` resolves to the current project when run inside the repo. Filter to discussions where `.notes[0].resolvable == true` (non-resolvable notes are plain comments, not review threads).

**Reply to a thread:**
```
glab api projects/:id/merge_requests/<mr-iid>/discussions/<discussion-id>/notes -f body="Addressed in <commit-link>."
```

**Commit link format:** `https://<host>/<namespace>/<project>/-/commit/<sha>`

## Linear (diff threads)

Only relevant when this repo's PRs are wired into Linear's diff-review surface (see step 0 in [SKILL.md](SKILL.md)). All access is via the `mcp__linear__*` tools — use `ToolSearch` to load their exact schemas before calling, since they're versioned by the MCP server.

1. `mcp__linear__list_diffs` (or `get_diff`) — locate the diff object tied to this PR.
2. `mcp__linear__get_diff_threads` — list threads on that diff, each with its comments and resolved state.
3. `mcp__linear__save_diff_comment` — reply on a specific thread with the commit-link message.
4. Do **not** call `mcp__linear__resolve_diff_thread` — this skill only replies, per its rule of leaving resolution to reviewers.

Use `mcp__linear__get_user` (or the equivalent "me" lookup) to determine your own identity for the already-addressed check in step 3 of [SKILL.md](SKILL.md).

**Commit link format:** same as wherever the underlying code host is (GitHub/GitLab) — Linear diffs mirror a real PR/MR, they don't replace it.

## Detecting a resolving reply (step 3 of SKILL.md)

A comment counts as "the marker" if its body matches either:

- A commit URL: `/commit/[0-9a-f]{7,40}` (GitHub/GitLab format)
- A bare SHA of 7-40 hex characters

This is a plain text/regex check against comment bodies already fetched above — no extra API call needed.
