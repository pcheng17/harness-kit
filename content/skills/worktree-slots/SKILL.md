---
name: worktree-slots
description: "Worktree slots: reusable numbered git worktrees with warm build output. Use when taking a worktree for a branch, parking one once its PR merges or the work is abandoned, or pruning worktrees to reclaim disk."
---

Linked worktrees live in numbered **slots** beside the primary checkout: `~/dev/foo` gets `~/dev/foo-wt-00`, `~/dev/foo-wt-01` and so on. A slot's path never changes, so its build output stays configured and warm when a later branch reuses it.

Run the `wt.sh` beside this file, from anywhere inside the repository (the primary checkout or any worktree), e.g. `~/.claude/skills/worktree-slots/wt.sh take my-branch` (`~/.agents/skills/worktree-slots/wt.sh` on Pi and Codex).

## Slot states

| State | Meaning | `take` |
| --- | --- | --- |
| Free | detached, unlocked, clean | reuses it |
| Done | on a branch whose PR is merged, unlocked, clean | reuses it and deletes that local branch |
| Busy | locked, uncommitted changes (submodules included), or a branch with an open, closed or no PR | skips it |

A branch counts as merged only when `gh` reports a merged PR for it (squash merges hide the branch from git), so without an authenticated `gh` every slot on a branch stays busy.

## Subcommands

- `take <branch>` puts the branch in a slot and prints the slot path on the last line of stdout. It reuses the lowest free slot, then the lowest done slot, and otherwise creates the lowest missing slot, cloning submodules from the primary checkout. A new branch starts at `origin/main`; an existing local branch is checked out as it is; a branch already checked out somewhere just prints that path. The slot is locked with the branch name as the reason.
- `park [path]` frees a slot (default: the one you are in): it detaches at `origin/main` and unlocks, keeping the local branch. It refuses the primary checkout and a tree with uncommitted changes.
- `list` shows each slot with its branch, lock reason, uncommitted changes and PR state.
- `prune [--keep k]` reclaims disk. It removes free and done slots, highest-numbered first, keeping the lowest `k` free ones. It also removes **legacy** worktrees (any other linked worktree that is a sibling of the primary checkout, such as an older `../<repo>-<branch>`) that are unlocked, clean and on a branch whose PR is merged, and prints why it keeps each other one; `--keep` does not apply to them. It deletes only local branches whose PR is merged and lists the other branches not checked out anywhere. Other worktrees are never touched.

## Working in a slot

`cd` to the path `take` prints and work there. Park the slot with `wt.sh park` once the PR is merged or the work is abandoned, so the next `take` can reuse it.

## Per-repo setup hook

When `take` creates a new slot (not when it reuses one) and the slot has an executable `.worktree-setup` at the repo root, it runs that file with the slot as the working directory, e.g. to configure a build. The slot is locked before the hook runs; if the hook fails, `take` fails naming the slot, which stays held for the branch. Fix the cause and run `./.worktree-setup` in the slot yourself; a second `take` of the branch only prints the path.

## Disk warning

Creating a slot and `list` warn when the slots together exceed `WT_WARN_GIB` GiB (default 100).
