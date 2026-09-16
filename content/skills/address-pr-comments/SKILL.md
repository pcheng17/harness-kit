---
name: address-pr-comments
description: Walk through all of a pull/merge request's unresolved review comment threads with the user — scan every thread, discuss each one and get the user's decision, then execute the agreed plan (one commit per thread, reply on the thread with a link to the resolving commit). Threads are never resolved/closed on the platform; that's left to the reviewer. Use when the user wants to "address PR comments", "resolve review feedback", "go through the review threads", "triage the review comments", or work through a specific PR/MR's comments interactively.
---

# Address PR Comments

Work through a pull/merge request's unresolved review threads in **two phases**:

1. **Discuss** — scan *every* unresolved thread, then walk them one at a time. For each, show the context, offer an analysis and a concrete suggestion, and get the user's decision. **No code is touched in this phase.**
2. **Execute** — carry out the agreed plan: one commit per thread, push, then reply on each thread with a link to the commit that resolved it.

That reply is the traceability marker — it tells reviewers exactly where the resolution happened, and tells a future run of this skill that the thread has already been handled.

This skill never resolves/closes threads on the platform itself — replying with the commit link is as far as it goes. Leave the actual "mark resolved" click to the human reviewer once they've confirmed the fix.

## Reference doc

[REVIEW-THREADS.md](REVIEW-THREADS.md) — exact fetch/reply mechanics per platform (GitHub, GitLab, Linear diffs). Read it before touching any platform API; don't guess at endpoints.

## 0. Figure out where the code review lives

Code review threads live wherever the PR/MR itself lives, which is not always the same place as the issue tracker (e.g. issues in Linear, code on GitHub). Resolve the host in this order:

1. If `docs/agents/issue-tracker.md` exists (written by `/setup-pcheng-skills`) and names GitHub or GitLab, use that.
2. If it names Linear, check whether this repo's PRs are wired into Linear's diff-review tools (`mcp__linear__list_diffs` returning results for this repo). If so, use Linear. If not, Linear only tracks issues here — fall back to step 3 for where the code lives.
3. Infer from `git remote -v` (`github.com` → GitHub, `gitlab.com` or a self-hosted GitLab host → GitLab).
4. If still unclear, ask the user.

## 1. Identify the PR/MR

If the user didn't name one, default to the PR/MR associated with the current branch. Confirm before proceeding if there's any doubt which one they mean.

If the working tree isn't on the PR/MR's branch, switch to it and pull the latest first. **Stop** if there are uncommitted changes (`git status --porcelain` is non-empty) and ask the user to commit or stash before continuing.

## 2. Fetch every thread and filter to candidates

Pull all review threads with full comment history and resolution state (see [REVIEW-THREADS.md](REVIEW-THREADS.md)). Also resolve "who am I" on the platform (your authenticated login) — needed for the already-handled check below.

A thread is **already handled** and should be skipped if either:

- The platform already shows it as resolved (or outdated), **or**
- The last comment in the thread is from you and its body contains a commit link or SHA (the marker this skill posts in Phase B) — unless a reviewer has commented *after* that reply, in which case they've pushed back and it needs another pass.

Also skip threads that are purely praise/acknowledgement with nothing to act on, or that reference a file no longer in the working tree.

Everything else is a **candidate**. Order the candidates **oldest first** (by the thread's first comment). If none remain, report "No unresolved review comments to address" and stop.

## Phase A — Discuss (no code changes)

First, print a numbered summary so the user has the whole picture up front:

```
Found {N} unresolved threads on {PR/MR ref}:

1. `{path}:{line}` — @{reviewer}: "{first ~80 chars}…"
2. `{path}:{line}` — @{reviewer}: "{first ~80 chars}…"
…
```

Then go through each candidate **one at a time**, in order. For each:

### a. Show the full context

- The file path and line number
- The relevant code (read the file and show the surrounding lines as they are *now*)
- The reviewer's comment, plus any later replies in the thread

### b. Offer analysis and a suggestion

- Explain what the reviewer is asking for.
- Suggest a concrete approach — what code to change and how. If there are multiple reasonable approaches, describe the alternatives briefly.
- If the ask is ambiguous (an open question, a suggestion you'd contest, a nitpick with no obvious resolution, or anything with more than one reasonable interpretation), say so and suggest what you'd ask the reviewer.

### c. Ask the user what to do

Use the harness's structured question tool (`ask_user_question` in Pi or `AskUserQuestion` in Claude Code, for example) to get an explicit decision. Do not use a plain-text prompt when a structured question tool is available. Only fall back to a plain prompt in a non-interactive environment or a harness without such a tool.

Present these options:

- **Apply** — apply your suggestion as described.
- **Skip** — the user will handle it manually; leave the thread completely untouched (no code change, no reply). Don't re-ask about it later in this same run.
- **Reply to reviewer** — draft a reply asking for clarification instead of changing code (the user approves the text).

Put your recommended option first and append `(Recommended)` to its label. This may be **Reply to reviewer** rather than **Apply** when the request is ambiguous or contested.

The user provides a modified approach through the tool's automatic custom-answer path. Do not add `Modify approach`, `Other`, `Type something.`, or an equivalent option yourself when the structured tool supplies that path automatically.

### d. Record the decision

Store a plan entry per thread — enough to execute without re-deciding:

- `thread_id`, `path`, `line`, the first comment's reply target (see [REVIEW-THREADS.md](REVIEW-THREADS.md)), `reviewer_login`
- `action`: one of `change`, `skip`, `reply`
- `plan`: the agreed change description, or the exact reply text

**Do not make any code changes during this phase.** Continue until every candidate has been discussed.

### e. Recap and confirm

Print the plan and get one confirmation before executing:

```
Plan for {PR/MR ref}:

Will change ({count}):
- `{path}:{line}` — {short plan}

Will reply to reviewer ({count}):
- `{path}:{line}` — {gist of reply}

Will skip ({count}):
- `{path}:{line}`
```

Use the structured question tool to ask the user to confirm before proceeding to Phase B when one is available; otherwise use a plain confirmation prompt.

## Phase B — Execute

Process the `change` threads one at a time, in file order:

### a. Implement

Make exactly the change the plan calls for — nothing beyond that thread's scope. Don't bundle unrelated cleanup into the fix.

### b. Commit

One commit per thread. Follow this repo's/user's commit conventions, and format before committing (e.g. `git rbx format` in Roblox repos, or whatever this repo uses). The commit message should describe the change itself, not reference "PR comment #N" (that association lives in the reply, not the commit).

If a single commit incidentally also resolves another open candidate (common when two reviewers flag the same code), that's fine — reply to both threads with the same commit link in step d rather than making a redundant commit. Track `thread_id → commit_sha`.

If a change turns out to be unclear or the file has diverged from what the plan assumed, **stop and ask the user** — don't silently skip or guess.

### c. Push

Once all `change` commits are made, push the branch (regular push only — never force-push; if the remote has moved, rebase and push again, and if it still fails, stop and tell the user). Push **before** replying so the commit links in step d actually resolve.

### d. Reply with the resolving commit link

For each addressed thread, reply **on that specific thread** (not a general PR comment) with a short message linking the commit:

> Addressed in <commit link>.

Get the exact reply mechanics and commit-link format for the host platform from [REVIEW-THREADS.md](REVIEW-THREADS.md). Never post this reply if the commit failed.

### e. Send the clarification replies

For each `reply` thread, post the user-approved clarification text on that thread.

## Wrap up

Summarize:

- **Addressed** — each thread with its commit link
- **Replied to reviewer** — each thread with the gist of the reply
- **Skipped** — threads left untouched at the user's direction

Do **not** resolve/close any thread — that's the reviewer's call.
