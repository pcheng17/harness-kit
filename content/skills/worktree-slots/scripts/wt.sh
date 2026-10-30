#!/usr/bin/env bash
# Slot-based worktree allocation. See ../SKILL.md.
#
# Linked worktrees live in fixed slots at ../<primary>-wt-<kk> beside the primary checkout, so a
# slot's build output stays warm when a later branch reuses it. A slot is free (detached, unlocked,
# clean), done (on a branch whose PR is merged, unlocked, clean) or busy (anything else). Only prune
# touches other worktrees, and only legacy ones beside the primary checkout.
set -euo pipefail

primary=""
slot_prefix=""
# Total slot disk use, in GiB, above which creating a slot and list print a warning.
warn_gib="${WT_WARN_GIB:-100}"

usage() {
    echo "usage: $0 take <branch> | park [path] | list | prune [--keep k]" >&2
    exit 2
}

die() {
    echo "worktree: $*" >&2
    exit 1
}

[[ "$warn_gib" =~ ^[0-9]+$ ]] || die "WT_WARN_GIB must be a whole number of GiB"

# Finds the primary checkout from any worktree of the repository containing <dir>.
find_primary() {
    primary="$(git -C "$1" worktree list --porcelain | sed -n '1s/^worktree //p')"
    [ -n "$primary" ] || die "$1 is not inside a git repository"
    slot_prefix="$primary-wt-"
}

slot_path() {
    printf '%s%02d' "$slot_prefix" "$1"
}

# Prints "<k> <path> <branch or empty> <locked: 0/1> <lock reason>" for each linked worktree directly
# beside the primary checkout (a sibling directory), where k is the slot number, or -1 for a legacy
# (non-slot) worktree. Fields are separated by \x1f, which unlike a tab keeps empty fields under read.
linked_worktrees() {
    git -C "$primary" worktree list --porcelain | awk -v primary="$primary" -v parent="$(dirname "$primary")/" -v prefix="$slot_prefix" '
        function flush() {
            rest = substr(path, length(parent) + 1)
            if (path != "" && path != primary && index(path, parent) == 1 && index(rest, "/") == 0) {
                k = substr(path, length(prefix) + 1)
                if (index(path, prefix) != 1 || k !~ /^[0-9][0-9]+$/) k = -1
                printf "%d\037%s\037%s\037%d\037%s\n", k, path, branch, locked, reason
            }
            path = ""; branch = ""; locked = 0; reason = ""
        }
        /^worktree / { flush(); path = substr($0, 10) }
        /^branch /   { branch = substr($0, 19) }
        /^locked/    { locked = 1; reason = substr($0, 8) }
        END          { flush() }
    '
}

# Prints linked_worktrees records for the slots only, sorted by slot number.
slots() {
    linked_worktrees | awk -F'\037' '$1 >= 0' | sort -n
}

# Succeeds when the worktree has uncommitted changes, or cannot be read (e.g. its directory is gone).
is_dirty() {
    local status
    status="$(git -C "$1" status --porcelain --ignore-submodules=none 2>/dev/null)" || return 0
    [ -n "$status" ]
}

gh_ok=1
# Records whether gh can answer PR queries, saying so once when it cannot. Runs in the main shell
# because pr_state is called from command substitutions, whose assignments would be lost.
check_gh() {
    if ! command -v gh >/dev/null || ! gh auth status >/dev/null 2>&1; then
        gh_ok=0
        echo "worktree: gh is missing or unauthenticated; slots on a branch count as busy" >&2
    fi
}

# Prints the branch's PR state: MERGED when a PR merged and none is open, OPEN, CLOSED, NONE, or
# UNKNOWN when gh is unavailable.
pr_state() {
    local states
    if [ "$gh_ok" -eq 0 ] ||
        ! states="$(cd "$primary" && gh pr list --state all --head "$1" --json state --jq '.[].state')"; then
        echo UNKNOWN
        return
    fi
    if grep -qx OPEN <<<"$states"; then
        echo OPEN
    elif grep -qx MERGED <<<"$states"; then
        echo MERGED
    elif [ -n "$states" ]; then
        echo CLOSED
    else
        echo NONE
    fi
}

# Prints free, done or busy for one slot.
slot_state() {
    local path="$1" branch="$2" locked="$3"
    if [ "$locked" -eq 1 ] || is_dirty "$path"; then
        echo busy
    elif [ -z "$branch" ]; then
        echo free
    elif [ "$(pr_state "$branch")" = MERGED ]; then
        echo "done"
    else
        echo busy
    fi
}

warn_disk_use() {
    local kib dirs
    dirs=("$slot_prefix"[0-9][0-9]*)
    [ -e "${dirs[0]}" ] || return 0
    kib="$(du -sk "${dirs[@]}" 2>/dev/null | awk '{ s += $1 } END { print s + 0 }' || true)"
    if [ "$kib" -gt $((warn_gib * 1024 * 1024)) ]; then
        echo "worktree: slots use $((kib / 1024 / 1024)) GiB (over WT_WARN_GIB=$warn_gib); consider '$0 prune'" >&2
    fi
}

# Checks out the submodule commits a worktree's HEAD records, fetching from the primary checkout's
# clones rather than the .gitmodules remote, which may be unreachable (e.g. no SSH key for GitHub).
update_submodules() {
    local path="$1" key sub_path name
    shift
    local url_overrides=()
    while read -r key sub_path; do
        name="${key#submodule.}"
        name="${name%.path}"
        url_overrides+=(-c "submodule.$name.url=$primary/$sub_path")
    done < <(git config -f "$path/.gitmodules" --get-regexp '^submodule\..*\.path$' || true)
    # Git refuses a local-path submodule URL over the file transport by default.
    # The +-guard keeps an empty array legal under set -u on bash older than 4.4 (stock macOS).
    git -C "$path" -c protocol.file.allow=always ${url_overrides[@]+"${url_overrides[@]}"} submodule update "$@" --recursive
}

# Sets <branch>'s upstream to origin/<branch>. Written directly because --track refuses a ref that
# the remote's fetch refspec does not map, as in a clone that fetches only main.
track_origin() {
    git -C "$primary" config "branch.$1.remote" origin
    git -C "$primary" config "branch.$1.merge" "refs/heads/$1"
}

# Fast-forwards <branch>, just checked out in slot <path>, to origin/<branch> when strictly behind
# it, and warns when the two have diverged. An equal or ahead branch is left as it is. Moving the
# branch only after git agreed to check it out keeps a branch busy elsewhere (e.g. mid-rebase in
# another worktree, which worktree list shows as detached) from being touched.
follow_origin() {
    local path="$1" branch="$2" remote="refs/remotes/origin/$2"
    if git -C "$path" merge-base --is-ancestor "$remote" HEAD; then
        return
    elif git -C "$path" merge-base --is-ancestor HEAD "$remote"; then
        git -C "$path" merge --ff-only --quiet "$remote"
        echo "worktree: fast-forwarded $branch to origin/$branch"
    else
        echo "worktree: warning: $branch and origin/$branch have diverged; checking out $branch as it is"
    fi
}

# Puts <branch> in a slot and prints the slot path last on stdout.
take() {
    local branch="$1" existing k path slot_branch locked registered branch_exists=0 remote_exists=0
    local chosen="" chosen_branch="" created=0 rc=0
    git check-ref-format --branch "$branch" >/dev/null || die "invalid branch name '$branch'"

    existing="$(git -C "$primary" worktree list --porcelain |
        awk -v ref="branch refs/heads/$branch" '/^worktree / { w = substr($0, 10) } $0 == ref { print w }')"
    # A live worktree is left alone, so its branch is not fast-forwarded to origin.
    if [ -n "$existing" ]; then
        echo "worktree: $branch is already checked out" >&2
        echo "$existing"
        return
    fi

    {
        check_gh
        git -C "$primary" fetch origin main
        # Asking origin directly ignores a stale origin/<branch> whose remote branch is gone; exit 2
        # means absent, anything else nonzero is a failure, not a reason to fork from main.
        git -C "$primary" ls-remote --exit-code origin "refs/heads/$branch" >/dev/null || rc=$?
        case "$rc" in
            0) remote_exists=1 ;;
            2) ;;
            *) die "cannot ask origin about $branch (git ls-remote exit $rc)" ;;
        esac
        # The explicit refspec updates origin/<branch> even under a narrow fetch config.
        if [ "$remote_exists" -eq 1 ]; then
            git -C "$primary" fetch --quiet origin "+refs/heads/$branch:refs/remotes/origin/$branch" ||
                die "cannot fetch $branch from origin"
        fi
        # Submodules clone from the primary checkout's clones, so refresh those first.
        git -C "$primary" submodule foreach --quiet 'git fetch --quiet origin'
        if git -C "$primary" show-ref --verify --quiet "refs/heads/$branch"; then
            branch_exists=1
        fi

        # Free slots first, so gh is asked about branch slots only when no free slot exists.
        while IFS=$'\x1f' read -r k path slot_branch locked _; do
            if [ -z "$slot_branch" ] && [ "$(slot_state "$path" "" "$locked")" = free ]; then
                chosen="$path"
                break
            fi
        done < <(slots)
        if [ -z "$chosen" ]; then
            while IFS=$'\x1f' read -r k path slot_branch locked _; do
                if [ -n "$slot_branch" ] && [ "$(slot_state "$path" "$slot_branch" "$locked")" = "done" ]; then
                    chosen="$path"
                    chosen_branch="$slot_branch"
                    break
                fi
            done < <(slots)
        fi

        if [ -n "$chosen" ]; then
            if [ "$branch_exists" -eq 1 ]; then
                # A failed checkout leaves the slot as it was: unlocked, and still free or done.
                git -C "$chosen" checkout "$branch"
                if [ "$remote_exists" -eq 1 ]; then
                    follow_origin "$chosen" "$branch"
                fi
            elif [ "$remote_exists" -eq 1 ]; then
                git -C "$chosen" checkout --no-track -b "$branch" "refs/remotes/origin/$branch"
                track_origin "$branch"
            else
                git -C "$chosen" checkout -b "$branch" refs/remotes/origin/main
            fi
            update_submodules "$chosen"
            if [ -n "$chosen_branch" ]; then
                git -C "$primary" branch -D "$chosen_branch"
            fi
        else
            registered="$(git -C "$primary" worktree list --porcelain)"
            k=0
            while [ -e "$(slot_path "$k")" ] || grep -qxF "worktree $(slot_path "$k")" <<<"$registered"; do
                k=$((k + 1))
            done
            chosen="$(slot_path "$k")"
            if [ "$branch_exists" -eq 1 ]; then
                # A refused add creates no slot.
                git -C "$primary" worktree add "$chosen" "$branch"
                if [ "$remote_exists" -eq 1 ]; then
                    follow_origin "$chosen" "$branch"
                fi
            elif [ "$remote_exists" -eq 1 ]; then
                git -C "$primary" worktree add --no-track -b "$branch" "$chosen" "refs/remotes/origin/$branch"
                track_origin "$branch"
            else
                git -C "$primary" worktree add -b "$branch" "$chosen" refs/remotes/origin/main
            fi
            update_submodules "$chosen" --init
            warn_disk_use
            created=1
        fi
        git -C "$primary" worktree lock --reason "$branch" "$chosen"
        # The slot is locked first so a failed hook leaves it held for the branch.
        if [ "$created" -eq 1 ] && [ -x "$chosen/.worktree-setup" ]; then
            (cd "$chosen" && ./.worktree-setup) || die ".worktree-setup failed in $chosen"
        fi
    } >&2
    echo "$chosen"
}

# Prints the top of the worktree containing <dir>, climbing out of any submodule.
worktree_root() {
    local root super
    root="$(git -C "$1" rev-parse --show-toplevel)" || die "$1 is not inside a git repository"
    while super="$(git -C "$root" rev-parse --show-superproject-working-tree)" && [ -n "$super" ]; do
        root="$super"
    done
    echo "$root"
}

# Detaches a slot at origin/main and unlocks it, leaving its branch alone.
park() {
    local path="$1" k slot locked found=""
    [ "$path" != "$primary" ] || die "refusing to park the primary checkout"
    while IFS=$'\x1f' read -r k slot _ locked _; do
        [ "$slot" = "$path" ] && found="$locked"
    done < <(slots)
    [ -n "$found" ] || die "$path is not a worktree slot"
    ! is_dirty "$path" || die "$path has uncommitted changes"

    git -C "$primary" fetch origin main
    git -C "$path" checkout --detach refs/remotes/origin/main
    update_submodules "$path"
    if [ "$found" -eq 1 ]; then
        git -C "$primary" worktree unlock "$path"
    fi
    echo "Parked $path" >&2
}

list() {
    local k path branch locked reason dirty pr
    check_gh
    {
        printf '%s\t%s\t%s\t%s\t%s\t%s\n' SLOT PATH BRANCH LOCKED DIRTY PR
        while IFS=$'\x1f' read -r k path branch locked reason; do
            dirty=no
            is_dirty "$path" && dirty=yes
            pr=-
            [ -n "$branch" ] && pr="$(pr_state "$branch")"
            if [ "$locked" -eq 1 ]; then
                reason="${reason:-yes}"
            else
                reason=-
            fi
            printf '%02d\t%s\t%s\t%s\t%s\t%s\n' "$k" "$path" "${branch:-free}" "$reason" "$dirty" "$pr"
        done < <(slots)
    } | column -t -s $'\t'
    warn_disk_use
}

# Removes free and done slots, highest-numbered first, keeping the lowest <keep> free ones, and legacy
# (non-slot) worktrees that are unlocked, clean and on a merged branch, saying why it keeps the rest.
prune() {
    local keep=0 k path branch locked state kept=0 left i reason
    local paths=() branches=()
    if [ $# -gt 0 ]; then
        [ "$1" = --keep ] && [ $# -eq 2 ] && [[ "$2" =~ ^[0-9]+$ ]] || usage
        keep="$2"
    fi
    check_gh

    while IFS=$'\x1f' read -r k path branch locked _; do
        state="$(slot_state "$path" "$branch" "$locked")"
        if [ "$state" = free ]; then
            if [ "$kept" -lt "$keep" ]; then
                kept=$((kept + 1))
            else
                paths+=("$path")
                branches+=("")
            fi
        elif [ "$state" = "done" ]; then
            paths+=("$path")
            branches+=("$branch")
        fi
    done < <(slots)

    while IFS=$'\x1f' read -r k path branch locked _; do
        if [ "$locked" -eq 1 ]; then
            reason=locked
        elif [ ! -d "$path" ]; then
            reason="directory missing"
        elif is_dirty "$path"; then
            reason="uncommitted changes"
        elif [ -z "$branch" ]; then
            reason=detached
        elif state="$(pr_state "$branch")" && [ "$state" != MERGED ]; then
            reason="PR $state"
        else
            paths+=("$path")
            branches+=("$branch")
            continue
        fi
        echo "Kept $path: $reason"
    done < <(linked_worktrees | awk -F'\037' '$1 < 0')

    # In reverse, so slots go highest-numbered first.
    for ((i = ${#paths[@]} - 1; i >= 0; i--)); do
        path="${paths[i]}"
        branch="${branches[i]}"
        # Initialized submodules make git refuse a plain remove; the clean check above makes
        # --force safe.
        git -C "$primary" worktree remove --force "$path"
        echo "Removed $path"
        if [ -n "$branch" ]; then
            git -C "$primary" branch -D "$branch"
        fi
    done

    left="$(git -C "$primary" for-each-ref --format='%(refname:short)%09%(worktreepath)' refs/heads |
        awk -F'\t' '$2 == "" && $1 != "main" { print "  " $1 }')"
    if [ -n "$left" ]; then
        echo "Local branches not checked out in any worktree (left alone):"
        echo "$left"
    fi
}

[ $# -gt 0 ] || usage
command="$1"
shift
case "$command" in
    take) [ $# -eq 1 ] || usage; find_primary .; take "$1" ;;
    park)
        [ $# -le 1 ] || usage
        root="$(worktree_root "${1:-.}")"
        find_primary "$root"
        park "$root"
        ;;
    list) [ $# -eq 0 ] || usage; find_primary .; list ;;
    prune) find_primary .; prune "$@" ;;
    *) usage ;;
esac
