---
name: cleanup-merged-worktree
description: "Use when the pull request for the current git worktree's branch has been merged and the user wants it cleaned up — deletes the worktree, switches the primary checkout back to main, updates main, and deletes the now-merged local branch. Local cleanup only; never touches the remote branch."
---

# Cleanup Merged Worktree

Delete a git worktree whose branch has already been merged, bring the primary checkout back to an up-to-date `main`, and delete the local branch. This is local cleanup only — the remote branch is never touched.

Every phase below has a **stop** condition. When one triggers, report it and take no further action; do not skip ahead or "fix it yourself" (e.g. never force-push, never `--force` a worktree removal, never escalate `branch -d` to `-D`).

## 0. Establish context

- Determine the branch to clean up: use the one the user named, otherwise `git branch --show-current` run from the worktree.
- **Stop** if that's `main`, empty, or detached — ask the user which worktree/branch they mean.
- Find the primary checkout with `git worktree list --porcelain` (the first `worktree <path>` entry is always the primary checkout; call it `$MAIN_PATH`). **Stop** if the worktree being cleaned up is itself `$MAIN_PATH` — this skill only removes linked worktrees, not the primary checkout.

## 1. Verify the PR was actually merged

Run `gh pr view <branch> --json state,url,mergedAt`.

- `gh` missing or not authenticated → **stop**, tell the user to run `gh auth login` (or install `gh`) and retry. Do not fall back to a local merge check.
- No PR found for the branch → **stop**, report there's nothing to verify against, and don't delete anything.
- `state` is not `MERGED` → **stop**, report the PR's URL and actual state (e.g. `OPEN`, `CLOSED`).

Only proceed past this step when `state == MERGED`.

## 2. Pre-flight safety check on the worktree

Even with a merged PR confirmed, check the worktree itself hasn't drifted:

- `git -C <worktree-path> status --porcelain` — if non-empty, **stop**, show the changes, and ask the user to commit, stash, or explicitly confirm discarding them.
- Check for commits not on the remote/not part of the merged PR (`git -C <worktree-path> log @{u}.. --oneline`, or `git -C <worktree-path> cherry -v origin/<branch>` if there's no upstream). If any exist, **stop** and list them — a merged PR only vouches for what was actually pushed.

## 3. Remove the worktree

Run `git -C <main-path> worktree remove <worktree-path>` — **from the primary checkout via `-C`, never from inside the worktree being removed**, and **never pass `--force`**. If removal fails because git detects changes on its own, surface that error rather than retrying with `--force`.

If the worktree directory is already gone (not listed by `git worktree list`), skip this step and continue.

## 4. Switch the primary checkout to `main` and update it

```
git -C <main-path> checkout main
git -C <main-path> fetch origin main
git -C <main-path> merge --ff-only origin/main
```

Fast-forward-only, not a plain `pull`: it deterministically brings `main` up to the merged remote state regardless of the user's local `pull.rebase`/`pull.ff` config, and never creates an unwanted merge commit. If the `merge --ff-only` fails because local `main` has diverged, **stop**, show `git -C <main-path> log main..origin/main --oneline` and `git -C <main-path> log origin/main..main --oneline`, and leave `main` untouched — never rebase or force-reset it unasked.

## 5. Delete the local branch

`git -C <main-path> branch -d <branch>` — lowercase `-d`, never `-D`. This doubles as a second safety net: git itself will refuse if the branch isn't actually merged into the current `HEAD`. If it refuses, **stop** and surface the message verbatim; this can legitimately happen after a squash merge (different SHAs), in which case tell the user that's expected and ask explicitly before ever using `-D` on their behalf.

## 6. Hand back control

The invoking process can't relocate the user's own shell out from under a directory that no longer exists. Print `$MAIN_PATH` and tell the user to `cd` there themselves, noting that any further commands at the old worktree path will fail since it's gone.

## Wrap up

On success:

```
Cleaned up `<branch>`:
- PR: <url> (MERGED)
- Worktree removed: <worktree-path>
- main updated: <old-sha>..<new-sha> (fast-forward from origin/main)
- Branch deleted: <branch>

Remote branch left untouched.
cd into `<main-path>` to continue — this session's old directory no longer exists.
```

If any step stopped early, report only that step's stop message — never a summary implying more happened than actually did.
