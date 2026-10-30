#!/usr/bin/env bash
# Black-box tests for the worktree-slots skill's wt.sh against throwaway repos and a stub gh.
# Usage: run.sh [path-to-wt.sh]   (default: the skill's wt.sh in this checkout)
# Each scenario builds its universe under $TMPDIR; all are removed when every check passes.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE="$(realpath "${1:-$HERE/../../content/skills/worktree-slots/scripts/wt.sh}")"
export PATH="$HERE/bin:$PATH"
export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1
# The primary checkout fetches its submodule from a local bare repo in this sandbox.
export GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=protocol.file.allow GIT_CONFIG_VALUE_0=always

fails=0
universes=()
pass() { echo "PASS: $1"; }
fail() { echo "FAIL: $1"; fails=$((fails + 1)); }
not() { ! "$@"; }
check() { local name="$1"; shift; if "$@"; then pass "$name"; else fail "$name"; fi; }

# Fresh universe: bare origin with a submodule, primary clone at $T/dev/proj.
setup() {
    T="$(mktemp -d "${TMPDIR:-/tmp}/wt-slots-test.XXXXXX")"
    universes+=("$T")
    export GH_STUB_DIR="$T/gh"
    mkdir -p "$GH_STUB_DIR" "$T/dev"
    git init -q --bare -b main "$T/proto.git"
    git clone -q "$T/proto.git" "$T/proto-seed" 2>/dev/null
    git -C "$T/proto-seed" commit -q --allow-empty -m proto
    git -C "$T/proto-seed" push -q origin main
    git init -q --bare -b main "$T/origin.git"
    git clone -q "$T/origin.git" "$T/seed" 2>/dev/null
    printf 'build/\n' >"$T/seed/.gitignore"
    git -C "$T/seed" -c protocol.file.allow=always submodule add -q "$T/proto.git" extern/proto 2>/dev/null
    git -C "$T/seed" add -A
    git -C "$T/seed" commit -q -m init
    git -C "$T/seed" push -q origin main
    git clone -q "$T/origin.git" "$T/dev/proj" 2>/dev/null
    P="$T/dev/proj"
    # Run a sandbox copy so nothing can resolve to the real repository the script came from.
    cp "$SOURCE" "$T/wt.sh"
    SCRIPT="$T/wt.sh"
    git -C "$P" -c protocol.file.allow=always submodule update -q --init --recursive 2>/dev/null
    # Point the submodule URL at something unreachable to prove the local-clone override is used.
    git -C "$P" config submodule.extern/proto.url /nonexistent/proto.git
}

take() { (cd "$P" && "$SCRIPT" take "$@"); }
wt() { (cd "$P" && "$SCRIPT" "$@"); }
slot() { echo "$T/dev/proj-wt-$1"; }
head_branch() { git -C "$1" symbolic-ref -q --short HEAD || echo detached; }
is_locked() { git -C "$P" worktree list --porcelain | awk -v p="$1" '$1=="worktree"{w=$2} $1=="locked" && w==p{f=1} END{exit !f}'; }
has_branch() { git -C "$P" rev-parse -q --verify "refs/heads/$1" >/dev/null; }
merged() { echo MERGED >"$GH_STUB_DIR/$1"; }

echo "== take on empty creates slot 00, prints path last, locks, inits submodule"
setup
wt list >/dev/null 2>&1; rc=$?
check "list with no slots succeeds" [ $rc -eq 0 ]
wt prune >/dev/null 2>&1; rc=$?
check "prune with no slots succeeds" [ $rc -eq 0 ]
out="$(take feat/a 2>/dev/null)"
check "last stdout line is slot 00" [ "$(tail -n1 <<<"$out")" = "$(slot 00)" ]
check "stdout is only the path" [ "$(wc -l <<<"$out")" -eq 1 ]
check "slot 00 on feat/a" [ "$(head_branch "$(slot 00)")" = feat/a ]
check "slot 00 locked" is_locked "$(slot 00)"
check "submodule checked out" [ -e "$(slot 00)/extern/proto/.git" ]
check "slot 00 clean" [ -z "$(git -C "$(slot 00)" status --porcelain --ignore-submodules=none)" ]

echo "== take of a branch already checked out prints its path and does nothing else"
out="$(take feat/a 2>/dev/null)"; rc=$?
check "exit 0" [ $rc -eq 0 ]
check "prints slot 00" [ "$(tail -n1 <<<"$out")" = "$(slot 00)" ]
check "no slot 01" [ ! -e "$(slot 01)" ]

echo "== park frees the slot, keeps the branch"
mkdir -p "$(slot 00)/build" && touch "$(slot 00)/build/warm"
(cd "$(slot 00)" && "$SCRIPT" park >/dev/null 2>&1)
check "slot 00 detached" [ "$(head_branch "$(slot 00)")" = detached ]
check "slot 00 unlocked" not is_locked "$(slot 00)"
check "feat/a still exists" has_branch feat/a
check "detached at origin/main" [ "$(git -C "$(slot 00)" rev-parse HEAD)" = "$(git -C "$P" rev-parse origin/main)" ]

echo "== take reuses the free slot with a warm build"
out="$(take feat/b 2>/dev/null)"
check "reused slot 00" [ "$(tail -n1 <<<"$out")" = "$(slot 00)" ]
check "warm marker survived" [ -e "$(slot 00)/build/warm" ]
check "on feat/b" [ "$(head_branch "$(slot 00)")" = feat/b ]

echo "== resume: take of an existing, unchecked-out branch checks it out"
git -C "$P" commit -q --allow-empty -m x 2>/dev/null
git -C "$P" branch feat/resume HEAD
out="$(take feat/resume 2>/dev/null)"
check "resume lands in slot 01" [ "$(tail -n1 <<<"$out")" = "$(slot 01)" ]
check "resume keeps its commit" [ "$(git -C "$(slot 01)" rev-parse HEAD)" = "$(git -C "$P" rev-parse feat/resume)" ]

echo "== busy slots are skipped; done slot is taken over and its branch deleted"
git -C "$P" worktree unlock "$(slot 01)"
merged feat-resume
git -C "$P" worktree unlock "$(slot 00)"
echo OPEN >"$GH_STUB_DIR/feat-b"
out="$(take feat/c 2>/dev/null)"
check "done slot 01 taken" [ "$(tail -n1 <<<"$out")" = "$(slot 01)" ]
check "merged branch deleted" not has_branch feat/resume
check "open-PR slot 00 untouched" [ "$(head_branch "$(slot 00)")" = feat/b ]

echo "== resume into a reused slot"
out="$(take feat/d 2>/dev/null)"   # slot 02
(cd "$(slot 02)" && "$SCRIPT" park >/dev/null 2>&1)
out="$(take feat/a 2>/dev/null)"
check "existing feat/a resumed in free slot 02" [ "$(tail -n1 <<<"$out")" = "$(slot 02)" ]
check "on feat/a" [ "$(head_branch "$(slot 02)")" = feat/a ]
(cd "$(slot 02)" && "$SCRIPT" park >/dev/null 2>&1)

echo "== dirty and no-PR slots are skipped"
touch "$(slot 02)/untracked"
out="$(take feat/e 2>/dev/null)"
check "dirty free slot skipped, creates 03" [ "$(tail -n1 <<<"$out")" = "$(slot 03)" ]
git -C "$P" worktree unlock "$(slot 03)"   # feat/e, no PR at all
out="$(take feat/f 2>/dev/null)"
check "no-PR slot skipped, creates 04" [ "$(tail -n1 <<<"$out")" = "$(slot 04)" ]

echo "== park refuses dirty tree and primary checkout"
(cd "$(slot 02)" && "$SCRIPT" park >/dev/null 2>&1); rc=$?
check "park dirty refused" [ $rc -ne 0 ]
(cd "$P" && "$SCRIPT" park >/dev/null 2>&1); rc=$?
check "park primary refused" [ $rc -ne 0 ]
rm "$(slot 02)/untracked"

echo "== gh unavailable: done slots treated as busy"
# Slot 02 is free; lock it so only the done slot 03 is a candidate.
git -C "$P" worktree lock "$(slot 02)"
merged feat-e
out="$(GH_STUB_UNAUTH=1 take feat/g 2>"$T/err")"
check "unauth skips done slot 03, creates 05" [ "$(tail -n1 <<<"$out")" = "$(slot 05)" ]
check "says gh unavailable" grep -q 'gh is missing or unauthenticated' "$T/err"
check "says it once" [ "$(grep -c 'gh is missing' "$T/err")" -eq 1 ]
git -C "$P" worktree unlock "$(slot 02)"

echo "== list shows every slot"
out="$(wt list 2>/dev/null)"
check "list mentions slots 00..05" bash -c 'for k in 00 01 02 03 04 05; do grep -q "proj-wt-$k" <<<"$1" || exit 1; done' _ "$out"
check "list marks free slot" grep -q free <<<"$out"
check "list shows MERGED" grep -q MERGED <<<"$out"

echo "== prune removes free and done slots, highest first, honouring --keep"
# State: 00 feat/b open; 01 feat/c locked; 02 free; 03 feat/e merged; 04 feat/f locked; 05 feat/g locked.
(cd "$(slot 05)" && "$SCRIPT" park >/dev/null 2>&1)   # 05 free; feat/g left behind
out="$(wt prune --keep 1 2>&1)"
check "free slot 02 kept (first free)" [ -d "$(slot 02)" ]
check "free slot 05 removed" [ ! -e "$(slot 05)" ]
check "done slot 03 removed" [ ! -e "$(slot 03)" ]
check "merged feat/e deleted" not has_branch feat/e
check "feat/g kept" has_branch feat/g
check "feat/g listed" grep -q feat/g <<<"$out"
check "busy slots kept" bash -c '[ -d "$1" ] && [ -d "$2" ] && [ -d "$3" ]' _ "$(slot 00)" "$(slot 01)" "$(slot 04)"
check "removed highest first" bash -c 'awk "/wt-05/{a=NR} /wt-03/{b=NR} END{exit !(a && b && a<b)}" <<<"$1"' _ "$out"
wt prune >/dev/null 2>&1
check "prune without --keep removes last free slot" [ ! -e "$(slot 02)" ]

echo "== take fills the lowest missing slot number"
out="$(take feat/h 2>/dev/null)"
check "creates lowest missing 02" [ "$(tail -n1 <<<"$out")" = "$(slot 02)" ]

echo "== non-slot worktrees are ignored"
git -C "$P" worktree add -q --detach "$T/dev/proj-other" 2>/dev/null
out="$(take feat/i 2>/dev/null)"
check "branch-named worktree not reused" [ "$(tail -n1 <<<"$out")" = "$(slot 03)" ]
wt prune >/dev/null 2>&1
check "branch-named worktree not pruned" [ -d "$T/dev/proj-other" ]
(cd "$T/dev/proj-other" && "$SCRIPT" park >/dev/null 2>&1); rc=$?
check "park refuses a non-slot worktree" [ $rc -ne 0 ]

echo "== numeric slot ordering past 99"
git -C "$P" worktree add -q --detach "$(slot 100)" 2>/dev/null
git -C "$P" worktree lock "$(slot 100)"
for k in $(seq 5 99); do mkdir -p "$(slot "$(printf %02d "$k")")"; done
out="$(take feat/j 2>/dev/null)"
check "creates 101 after 100" [ "$(tail -n1 <<<"$out")" = "$(slot 101)" ]
out="$(wt list 2>/dev/null)"
check "list sorts 100 after 04" bash -c 'awk "/wt-04 /{a=NR} /wt-100 /{b=NR} END{exit !(a && b && a<b)}" <<<"$1"' _ "$out"

echo "== park and take follow a submodule bump on origin/main"
git -C "$T/proto-seed" commit -q --allow-empty -m proto2
git -C "$T/proto-seed" push -q origin main
git -C "$T/seed" -C extern/proto pull -q origin main 2>/dev/null
git -C "$T/seed" commit -q -am "bump proto"
git -C "$T/seed" push -q origin main
(cd "$(slot 02)" && "$SCRIPT" park >/dev/null 2>&1); rc=$?
check "park succeeds after bump" [ $rc -eq 0 ]
check "parked slot clean after bump" [ -z "$(git -C "$(slot 02)" status --porcelain --ignore-submodules=none)" ]
check "parked submodule at bumped commit" [ "$(git -C "$(slot 02)/extern/proto" rev-parse HEAD)" = "$(git -C "$T/proto-seed" rev-parse HEAD)" ]
out="$(take feat/k 2>/dev/null)"
check "bumped free slot reused" [ "$(tail -n1 <<<"$out")" = "$(slot 02)" ]
check "reused slot clean" [ -z "$(git -C "$(slot 02)" status --porcelain --ignore-submodules=none)" ]

echo "== park from inside a submodule and by path from outside any repo"
take feat/m >/dev/null 2>&1   # lands in a free slot or a new one
m="$(git -C "$P" worktree list --porcelain | awk '/^worktree /{w=substr($0,10)} $0=="branch refs/heads/feat/m"{print w}')"
(cd "$m/extern/proto" && "$SCRIPT" park >/dev/null 2>&1)
check "park from submodule parks the slot" [ "$(head_branch "$m")" = detached ]
take feat/n >/dev/null 2>&1
(cd "$T" && "$SCRIPT" park "$m" >/dev/null 2>&1)
check "park by path outside a repo" [ "$(head_branch "$m")" = detached ]

echo "== list header lines up with rows"
out="$(wt list 2>/dev/null)"
# A function, not bash -c: bash 3.2 (stock macOS) misparses escaped quotes inside "$(...)".
aligned() { [ "$(head -n1 <<<"$1" | awk '{ print index($0, "PATH") }')" -eq "$(sed -n 2p <<<"$1" | awk '{ print index($0, "/") }')" ]; }
check "header is column-aligned" aligned "$out"

echo "== take asks gh nothing when a free slot exists"
: >"$GH_STUB_DIR/calls"
f="$(take feat/q 2>/dev/null | tail -n1)"   # whatever slot; then free it again and create a branch slot below it
(cd "$f" && "$SCRIPT" park >/dev/null 2>&1)
: >"$GH_STUB_DIR/calls"
take feat/r >/dev/null 2>&1
check "no gh pr list when a free slot exists" not grep -q 'pr list' "$GH_STUB_DIR/calls"

echo "== a registered slot whose directory vanished is not reused"
v="$(take feat/s 2>/dev/null | tail -n1)"
(cd "$v" && "$SCRIPT" park >/dev/null 2>&1)
rm -rf "$v"
out="$(take feat/t 2>/dev/null)"; rc=$?
check "take succeeds past a vanished slot" [ $rc -eq 0 ]
check "vanished slot not chosen" [ "$(tail -n1 <<<"$out")" != "$v" ]

echo "== invalid warn threshold is rejected up front"
WT_WARN_GIB=abc wt list >/dev/null 2>&1; rc=$?
check "non-numeric threshold fails" [ $rc -ne 0 ]

echo "== disk warning threshold"
out="$(WT_WARN_GIB=0 wt list 2>&1 >/dev/null)"
check "warns over threshold" grep -q 'WT_WARN_GIB' <<<"$out"

check "warning names the prune command" grep -q "wt.sh prune" <<<"$out"

echo "== prune removes merged, clean legacy worktrees and says why it keeps the rest"
legacy() { git -C "$P" worktree add -q -b "$2" "$1" origin/main 2>/dev/null; }
legacy "$T/dev/proj-merged" legacy/merged; merged legacy-merged
legacy "$T/dev/proj-dirty" legacy/dirty; merged legacy-dirty; touch "$T/dev/proj-dirty/untracked"
legacy "$T/dev/proj-open" legacy/open
legacy "$T/dev/proj-locked" legacy/locked; merged legacy-locked; git -C "$P" worktree lock "$T/dev/proj-locked"
mkdir -p "$T/elsewhere"
legacy "$T/elsewhere/proj-far" legacy/far; merged legacy-far
legacy "$P/nested" legacy/nested; merged legacy-nested
legacy "$T/dev/proj-gone" legacy/gone; merged legacy-gone; rm -rf "$T/dev/proj-gone"
out="$(wt prune --keep 99 2>&1)"; rc=$?
check "prune with legacy worktrees succeeds" [ $rc -eq 0 ]
check "merged clean legacy removed" [ ! -e "$T/dev/proj-merged" ]
check "its merged branch deleted" not has_branch legacy/merged
check "merged dirty legacy kept" [ -d "$T/dev/proj-dirty" ]
check "dirty reason given" grep -q "Kept $T/dev/proj-dirty: uncommitted changes" <<<"$out"
check "unmerged legacy kept" [ -d "$T/dev/proj-open" ]
check "unmerged reason given" grep -q "Kept $T/dev/proj-open: PR NONE" <<<"$out"
check "locked legacy kept" [ -d "$T/dev/proj-locked" ]
check "locked reason given" grep -q "Kept $T/dev/proj-locked: locked" <<<"$out"
check "detached legacy kept" grep -q "Kept $T/dev/proj-other: detached" <<<"$out"
check "worktree outside the parent directory ignored" bash -c '[ -d "$1" ] && ! grep -q proj-far <<<"$2"' _ "$T/elsewhere/proj-far" "$out"
check "worktree nested below the parent directory ignored" bash -c '[ -d "$1" ] && ! grep -q nested <<<"$2"' _ "$P/nested" "$out"
check "vanished legacy kept as missing" grep -q "Kept $T/dev/proj-gone: directory missing" <<<"$out"
check "primary never mentioned" not grep -q "$P:" <<<"$out"

echo "== .worktree-setup runs in a new slot, not on reuse, and its failure fails take"
setup
export HOOK_LOG="$T/hook.log" HOOK_FAIL="$T/hook-fail"
printf '#!/bin/sh\npwd -P >>"$HOOK_LOG"\n[ ! -e "$HOOK_FAIL" ]\n' >"$T/seed/.worktree-setup"
chmod +x "$T/seed/.worktree-setup"
git -C "$T/seed" add .worktree-setup
git -C "$T/seed" commit -q -m hook
git -C "$T/seed" push -q origin main
out="$(take feat/a 2>"$T/err")"; rc=$?
check "take with hook succeeds" [ $rc -eq 0 ]
check "stdout is only the path with a hook" [ "$out" = "$(slot 00)" ]
check "hook ran once, in the new slot" [ "$(cat "$HOOK_LOG")" = "$(realpath "$(slot 00)")" ]
(cd "$(slot 00)" && "$SCRIPT" park >/dev/null 2>&1)
take feat/b >/dev/null 2>&1
check "hook not run on reuse" [ "$(wc -l <"$HOOK_LOG")" -eq 1 ]
touch "$HOOK_FAIL"
out="$(take feat/c 2>"$T/err")"; rc=$?
check "failing hook fails take" [ $rc -ne 0 ]
check "failing hook is named with its slot" grep -q "worktree: .worktree-setup failed in $(slot 01)" "$T/err"
check "failing hook prints no path" [ -z "$out" ]
check "slot of a failed hook is held" is_locked "$(slot 01)"

echo "== take follows origin/<branch>, in a reused slot (r) and a new one (n)"
setup
# Pushes a commit on <parent> to origin as <branch> from the seed clone, so the primary has not
# fetched it, and prints the commit.
remote_commit() {
    local c
    c="$(git -C "$T/seed" commit-tree -p "$2" -m "remote $1" "$2^{tree}")"
    git -C "$T/seed" push -q origin "$c:refs/heads/$1"
    echo "$c"
}
# Makes local <branch> in the primary a new commit on <parent> and prints the commit.
local_commit() {
    local c
    c="$(git -C "$P" commit-tree -p "$2" -m "local $1" "$2^{tree}")"
    git -C "$P" branch -f "$1" "$c"
    echo "$c"
}
rev() { git -C "$1" rev-parse "$2"; }
upstream() { git -C "$1" rev-parse --abbrev-ref '@{u}' 2>/dev/null; }
# Slot 00 stays free for the r cases; slot 01 holds feat/hold so each n case creates slot 02.
take feat/free >/dev/null 2>&1
take feat/hold >/dev/null 2>&1
(cd "$(slot 00)" && "$SCRIPT" park >/dev/null 2>&1)
check "setup: slot 00 free" [ "$(head_branch "$(slot 00)")" = detached ]
check "setup: slot 01 held" is_locked "$(slot 01)"
main="$(git -C "$T/seed" rev-parse main)"
# Runs one case: take <branch> in the free slot 00 (r) or with slot 00 held, creating 02 (n).
# Leaves stdout in $out, stderr in $T/err and the slot in $s; finish frees the slot again.
run() {
    if [ "$2" = n ]; then git -C "$P" worktree lock "$(slot 00)"; s="$(slot 02)"; else s="$(slot 00)"; fi
    out="$(take "$1" 2>"$T/err")"; rc=$?
    [ "$2" = n ] && git -C "$P" worktree unlock "$(slot 00)"
    check "$1: take succeeds" [ $rc -eq 0 ]
    check "$1: last stdout line is the slot" [ "$(tail -n1 <<<"$out")" = "$s" ]
    check "$1: slot on the branch" [ "$(head_branch "$s")" = "$1" ]
}
finish() {
    (cd "$s" && "$SCRIPT" park >/dev/null 2>&1)
    [ "$s" = "$(slot 02)" ] && git -C "$P" worktree remove --force "$s"
    return 0
}
for m in r n; do
    b="remote-only-$m"; c="$(remote_commit "$b" main)"
    run "$b" "$m"
    check "$b: at origin's commit" [ "$(rev "$s" HEAD)" = "$c" ]
    check "$b: upstream is origin/$b" [ "$(upstream "$s")" = "origin/$b" ]
    finish

    b="behind-$m"; git -C "$P" branch -q "$b" origin/main; c="$(remote_commit "$b" main)"
    run "$b" "$m"
    check "$b: fast-forwarded to origin" [ "$(rev "$s" HEAD)" = "$c" ]
    check "$b: says it fast-forwarded" grep -q "fast-forwarded $b to origin/$b" "$T/err"
    finish

    b="ahead-$m"; r="$(remote_commit "$b" main)"
    git -C "$P" fetch -q origin "refs/heads/$b:refs/heads/$b"; c="$(local_commit "$b" "$b")"
    run "$b" "$m"
    check "$b: local commit kept" [ "$(rev "$s" HEAD)" = "$c" ]
    check "$b: origin untouched" [ "$(git -C "$T/origin.git" rev-parse "$b")" = "$r" ]
    check "$b: no warning" not grep -q warning "$T/err"
    finish

    b="diverged-$m"; r="$(remote_commit "$b" main)"; c="$(local_commit "$b" main)"
    run "$b" "$m"
    check "$b: local commit kept" [ "$(rev "$s" HEAD)" = "$c" ]
    check "$b: origin untouched" [ "$(git -C "$T/origin.git" rev-parse "$b")" = "$r" ]
    check "$b: warns naming both" grep -q "warning: $b and origin/$b have diverged" "$T/err"
    check "$b: warning not on stdout" [ "$(wc -l <<<"$out")" -eq 1 ]
    finish

    b="neither-$m"
    run "$b" "$m"
    check "$b: starts at origin/main" [ "$(rev "$s" HEAD)" = "$main" ]
    finish
done

echo "== take of a branch checked out in a slot leaves it alone even when origin is ahead"
old="$(rev "$P" refs/heads/feat/hold)"; remote_commit feat/hold main >/dev/null   # feat/hold is at main
out="$(take feat/hold 2>/dev/null)"
check "prints the holding slot" [ "$(tail -n1 <<<"$out")" = "$(slot 01)" ]
check "branch not moved" [ "$(rev "$P" refs/heads/feat/hold)" = "$old" ]

echo "== take refuses a behind branch stopped mid-rebase in another worktree, leaving it alone"
for m in r n; do
    b="rebasing-$m"; c="$(local_commit "$b" main)"
    git -C "$P" push -q origin "$b"
    git -C "$P" push -q origin "$(git -C "$P" commit-tree -p "$c" -m ahead "$c^{tree}"):refs/heads/$b"
    git -C "$P" worktree add -q "$T/dev/proj-$b" "$b" 2>/dev/null
    git -C "$T/dev/proj-$b" rebase --exec false HEAD~1 >/dev/null 2>&1
    check "$b: setup: worktree list shows it detached" [ "$(head_branch "$T/dev/proj-$b")" = detached ]
    [ "$m" = n ] && git -C "$P" worktree lock "$(slot 00)"
    out="$(take "$b" 2>"$T/err")"; rc=$?
    [ "$m" = n ] && git -C "$P" worktree unlock "$(slot 00)"
    check "$b: take fails" [ $rc -ne 0 ]
    check "$b: prints no path" [ -z "$out" ]
    check "$b: branch ref unchanged" [ "$(rev "$P" "refs/heads/$b")" = "$c" ]
    if [ "$m" = r ]; then
        check "$b: free slot left free" [ "$(head_branch "$(slot 00)")" = detached ]
        check "$b: free slot left unlocked" not is_locked "$(slot 00)"
    else
        check "$b: no slot created" [ ! -e "$(slot 02)" ]
    fi
    git -C "$T/dev/proj-$b" rebase --abort
    git -C "$P" worktree remove --force "$T/dev/proj-$b"
done

echo "== take dies, creating nothing, when origin cannot be asked or fetched"
# A git wrapper that fails any call whose arguments include $FAIL_GIT. It drops itself from PATH
# before running git, so a git on PATH that is itself a wrapper cannot call back into it.
mkdir -p "$T/gitstub"
# shellcheck disable=SC2016 # the single-quoted text is the wrapper's own script
printf '#!/usr/bin/env bash\ncase " $* " in *" $FAIL_GIT "*) echo "stub git: failing $*" >&2; exit 128 ;; esac\nPATH="${PATH#%q:}" exec git "$@"\n' \
    "$T/gitstub" >"$T/gitstub/git"
chmod +x "$T/gitstub/git"
out="$(PATH="$T/gitstub:$PATH" FAIL_GIT=ls-remote take ls-fails 2>"$T/err")"; rc=$?
check "failed ls-remote fails take" [ $rc -ne 0 ]
check "failed ls-remote is named" grep -q "cannot ask origin about ls-fails" "$T/err"
check "failed ls-remote creates no branch" not has_branch ls-fails
remote_commit fetch-fails main >/dev/null
out="$(PATH="$T/gitstub:$PATH" FAIL_GIT=+refs/heads/fetch-fails:refs/remotes/origin/fetch-fails take fetch-fails 2>"$T/err")"; rc=$?
check "failed branch fetch fails take" [ $rc -ne 0 ]
check "failed branch fetch is named" grep -q "cannot fetch fetch-fails from origin" "$T/err"
check "failed branch fetch creates no branch" not has_branch fetch-fails
git -C "$P" remote set-url origin "$T/nonexistent.git"
out="$(take unreachable 2>/dev/null)"; rc=$?
git -C "$P" remote set-url origin "$T/origin.git"
check "unreachable origin fails take" [ $rc -ne 0 ]
check "unreachable origin creates no branch" not has_branch unreachable
check "slot 00 still free" [ "$(head_branch "$(slot 00)")" = detached ]
check "slot 00 still unlocked" not is_locked "$(slot 00)"

echo "== a stale origin/<branch> whose remote branch is gone is ignored"
b=stale; remote_commit "$b" main >/dev/null
git -C "$P" fetch -q origin "+refs/heads/$b:refs/remotes/origin/$b"
git -C "$T/seed" push -q origin ":refs/heads/$b"
run "$b" r
check "$b: starts at origin/main" [ "$(rev "$s" HEAD)" = "$main" ]
check "$b: upstream is not the stale ref" [ "$(upstream "$s")" != "origin/$b" ]
finish

echo "== a local branch named origin/<branch> does not shadow the remote start point"
b=foo; git -C "$P" branch -q "origin/$b" main; c="$(remote_commit "$b" main)"
run "$b" r
check "$b: at origin's commit" [ "$(rev "$s" HEAD)" = "$c" ]
finish

echo "== take follows origin/<branch> in a done slot, deleting only the done slot's branch"
git -C "$P" worktree unlock "$(slot 01)"; merged feat-hold
git -C "$P" worktree lock "$(slot 00)"
b=behind-done; git -C "$P" branch -q "$b" origin/main; c="$(remote_commit "$b" main)"
out="$(take "$b" 2>/dev/null)"
git -C "$P" worktree unlock "$(slot 00)"
check "done slot 01 reused" [ "$(tail -n1 <<<"$out")" = "$(slot 01)" ]
check "$b: fast-forwarded in the done slot" [ "$(rev "$(slot 01)" HEAD)" = "$c" ]
check "done slot's merged branch deleted" not has_branch feat/hold
check "taken branch kept" has_branch "$b"

echo "== take of a remote-only branch via a done slot"
git -C "$P" worktree unlock "$(slot 01)"; merged behind-done
git -C "$P" worktree lock "$(slot 00)"
b=remote-done; c="$(remote_commit "$b" main)"
out="$(take "$b" 2>/dev/null)"
git -C "$P" worktree unlock "$(slot 00)"
check "done slot 01 reused" [ "$(tail -n1 <<<"$out")" = "$(slot 01)" ]
check "$b: at origin's commit" [ "$(rev "$(slot 01)" HEAD)" = "$c" ]
check "$b: upstream is origin/$b" [ "$(upstream "$(slot 01)")" = "origin/$b" ]
check "done slot's merged branch deleted" not has_branch behind-done

echo "== take of a remote-only branch under a fetch config that maps only main"
git -C "$P" config remote.origin.fetch '+refs/heads/main:refs/remotes/origin/main'
b=narrow; c="$(remote_commit "$b" main)"
run "$b" r
check "$b: at origin's commit" [ "$(rev "$s" HEAD)" = "$c" ]
check "$b: upstream branch configured" [ "$(git -C "$P" config "branch.$b.remote") $(git -C "$P" config "branch.$b.merge")" = "origin refs/heads/$b" ]

echo "== take of the primary checkout's branch leaves it alone even when origin is ahead"
old="$(rev "$P" refs/heads/main)"; remote_commit main main >/dev/null
out="$(take main 2>/dev/null)"
check "prints the primary checkout" [ "$(tail -n1 <<<"$out")" = "$P" ]
check "main not moved" [ "$(rev "$P" refs/heads/main)" = "$old" ]

echo "== a repository without submodules"
N="$(mktemp -d "${TMPDIR:-/tmp}/wt-slots-test.XXXXXX")"
universes+=("$N")
git init -q --bare -b main "$N/origin.git"
git clone -q "$N/origin.git" "$N/plain" 2>/dev/null
git -C "$N/plain" commit -q --allow-empty -m init
git -C "$N/plain" push -q origin main
out="$(cd "$N/plain" && "$SCRIPT" take feat/a 2>/dev/null)"; rc=$?
check "take without submodules succeeds" [ $rc -eq 0 ]
check "slot named after the primary" [ "$out" = "$N/plain-wt-00" ]
(cd "$out" && "$SCRIPT" park >/dev/null 2>&1); rc=$?
check "park without submodules succeeds" [ $rc -eq 0 ]

# Fresh universe, with its own gh stub state and script copy, whose origin has default branch master
# and a develop branch. The primary clone is at $M/dev/proj, with origin/HEAD set by the clone.
master_universe() {
    M="$(mktemp -d "${TMPDIR:-/tmp}/wt-slots-test.XXXXXX")"
    universes+=("$M")
    export GH_STUB_DIR="$M/gh"
    mkdir -p "$GH_STUB_DIR"
    cp "$SOURCE" "$M/wt.sh"
    SCRIPT="$M/wt.sh"
    git init -q --bare -b master "$M/origin.git"
    git clone -q "$M/origin.git" "$M/seed" 2>/dev/null
    git -C "$M/seed" commit -q --allow-empty -m init
    git -C "$M/seed" push -q origin master
    git -C "$M/seed" push -q origin "$(git -C "$M/seed" commit-tree -p master -m develop 'master^{tree}'):refs/heads/develop"
    git -C "$M/seed" fetch -q origin
    git clone -q "$M/origin.git" "$M/dev/proj" 2>/dev/null
    MP="$M/dev/proj"
}
mslot() { echo "$M/dev/proj-wt-$1"; }
mtake() { (cd "$MP" && "$SCRIPT" take "$@"); }
mrev() { git -C "$1" rev-parse "$2"; }
# Advances <branch> on origin from the seed clone, so the primary has not fetched it, and prints it.
madvance() {
    local c
    c="$(git -C "$M/seed" commit-tree -p "origin/$1" -m "advance $1" "origin/$1^{tree}")"
    git -C "$M/seed" push -q origin "$c:refs/heads/$1"
    git -C "$M/seed" fetch -q origin
    echo "$c"
}

echo "== a repository whose default branch is master, with origin/HEAD set"
master_universe
check "setup: origin/HEAD is origin/master" [ "$(git -C "$MP" symbolic-ref --short refs/remotes/origin/HEAD)" = origin/master ]
c="$(madvance master)"
out="$(mtake feat/a 2>"$M/err")"; rc=$?
check "take succeeds" [ $rc -eq 0 ]
check "slot 00 created" [ "$(tail -n1 <<<"$out")" = "$(mslot 00)" ]
check "new branch starts at the fetched origin/master" [ "$(mrev "$(mslot 00)" HEAD)" = "$c" ]
c="$(madvance master)"
(cd "$(mslot 00)" && "$SCRIPT" park >/dev/null 2>"$M/err"); rc=$?
check "park succeeds" [ $rc -eq 0 ]
check "parked at the fetched origin/master" [ "$(mrev "$(mslot 00)" HEAD)" = "$c" ]
check "parked detached" [ "$(head_branch "$(mslot 00)")" = detached ]
git -C "$MP" branch -q origin/master master   # makes symbolic-ref --short say remotes/origin/master
out="$(mtake feat/z 2>/dev/null)"; rc=$?
check "a local branch named origin/master does not confuse the base" [ $rc -eq 0 ]
(cd "$(mslot 00)" && "$SCRIPT" park >/dev/null 2>&1)
git -C "$MP" branch -q -D origin/master

echo "== a repository whose default branch is master, without origin/HEAD"
git -C "$MP" remote set-head origin -d
c="$(madvance master)"
out="$(mtake feat/b 2>/dev/null)"; rc=$?
check "take succeeds via ls-remote" [ $rc -eq 0 ]
check "new branch starts at origin/master" [ "$(mrev "$(tail -n1 <<<"$out")" HEAD)" = "$c" ]
(cd "$(mslot 00)" && "$SCRIPT" park >/dev/null 2>&1); rc=$?
check "park succeeds via ls-remote" [ $rc -eq 0 ]
check "parked at origin/master" [ "$(mrev "$(mslot 00)" HEAD)" = "$c" ]
mkdir -p "$M/gitstub"
printf '#!/usr/bin/env bash\ncase " $* " in *" $FAIL_GIT "*) exit 128 ;; esac\nPATH="${PATH#%q:}" exec git "$@"\n' \
    "$M/gitstub" >"$M/gitstub/git"
chmod +x "$M/gitstub/git"
out="$(PATH="$M/gitstub:$PATH" FAIL_GIT=--symref mtake feat/c 2>"$M/err")"; rc=$?
check "unresolvable default branch fails take" [ $rc -ne 0 ]
check "failure names WT_BASE_BRANCH" grep -q WT_BASE_BRANCH "$M/err"
check "unresolvable default branch creates no branch" not git -C "$MP" rev-parse -q --verify refs/heads/feat/c
(cd "$MP" && PATH="$M/gitstub:$PATH" FAIL_GIT=--symref "$SCRIPT" list >/dev/null 2>&1); rc=$?
check "list needs no default branch" [ $rc -eq 0 ]

echo "== WT_BASE_BRANCH overrides origin's default branch, under a fetch config that maps only master"
git -C "$MP" remote set-head origin master
git -C "$MP" config remote.origin.fetch '+refs/heads/master:refs/remotes/origin/master'
c="$(madvance develop)"
out="$(WT_BASE_BRANCH=develop mtake feat/d 2>/dev/null)"; rc=$?
check "take succeeds" [ $rc -eq 0 ]
check "new branch starts at the fetched origin/develop" [ "$(mrev "$(tail -n1 <<<"$out")" HEAD)" = "$c" ]
c="$(madvance develop)"
(cd "$(mslot 00)" && WT_BASE_BRANCH=develop "$SCRIPT" park >/dev/null 2>&1); rc=$?
check "park succeeds" [ $rc -eq 0 ]
check "parked at the fetched origin/develop" [ "$(mrev "$(mslot 00)" HEAD)" = "$c" ]
out="$(WT_BASE_BRANCH='bad..name' mtake feat/e 2>"$M/err")"; rc=$?
check "invalid WT_BASE_BRANCH fails take" [ $rc -ne 0 ]
check "invalid WT_BASE_BRANCH is named" grep -q WT_BASE_BRANCH "$M/err"

echo "== a bare primary with sibling worktrees, default branch master, with a submodule"
master_universe
git -C "$M/seed" -c protocol.file.allow=always submodule add -q "$T/proto.git" extern/proto 2>/dev/null
git -C "$M/seed" commit -q -m sub
git -C "$M/seed" push -q origin master
# The usual bare-worktree recipe: a bare clone given remote-tracking refs and origin/HEAD.
B="$M/ge"
git clone -q --bare "$M/origin.git" "$B/.bare" 2>/dev/null
git -C "$B/.bare" config remote.origin.fetch '+refs/heads/*:refs/remotes/origin/*'
git -C "$B/.bare" fetch -q origin
git -C "$B/.bare" remote set-head origin -a >/dev/null
git -C "$B/.bare" worktree add -q "$B/legacy" -b legacy/x origin/master 2>/dev/null
git -C "$B/.bare" branch -q stray origin/master
# The base branch's worktree is a legacy worktree here; a PR merged from a branch named master must
# not get it pruned.
git -C "$B/.bare" worktree add -q "$B/master" master 2>/dev/null
merged master
bslot() { echo "$B/ge-wt-$1"; }
out="$(cd "$B/.bare" && "$SCRIPT" take feat/a 2>"$M/err")"; rc=$?
check "take from the bare dir succeeds" [ $rc -eq 0 ]
check "slot named after the bare dir's parent" [ "$(tail -n1 <<<"$out")" = "$(bslot 00)" ]
check "no slot named after .bare" [ ! -e "$B/.bare-wt-00" ]
check "on feat/a at origin/master" [ "$(mrev "$(bslot 00)" HEAD)" = "$(mrev "$B/.bare" refs/remotes/origin/master)" ]
check "locked" bash -c 'git -C "$1" worktree list --porcelain | awk -v p="$2" "\$1==\"worktree\"{w=\$2} \$1==\"locked\" && w==p{f=1} END{exit !f}"' _ "$B/.bare" "$(bslot 00)"
check "submodule checked out" [ -e "$(bslot 00)/extern/proto/.git" ]
out="$(cd "$B/legacy" && "$SCRIPT" take feat/b 2>/dev/null)"; rc=$?
check "take from a sibling worktree succeeds" [ $rc -eq 0 ]
check "second slot is 01" [ "$(tail -n1 <<<"$out")" = "$(bslot 01)" ]
(cd "$(bslot 01)" && "$SCRIPT" park >/dev/null 2>&1); rc=$?
check "park succeeds" [ $rc -eq 0 ]
check "parked detached at origin/master" [ "$(mrev "$(bslot 01)" HEAD)" = "$(mrev "$B/.bare" refs/remotes/origin/master)" ]
check "parked slot clean" [ -z "$(git -C "$(bslot 01)" status --porcelain --ignore-submodules=none)" ]
(cd "$B/.bare" && "$SCRIPT" park "$B/.bare" >/dev/null 2>"$M/err"); rc=$?
check "park refuses the bare dir" [ $rc -ne 0 ]
check "park names the bare dir" grep -q "refusing to park the bare git dir" "$M/err"
out="$(cd "$B/.bare" && "$SCRIPT" list 2>/dev/null)"; rc=$?
check "list succeeds" [ $rc -eq 0 ]
check "list shows both slots" bash -c 'grep -q "ge-wt-00" <<<"$1" && grep -q "ge-wt-01" <<<"$1"' _ "$out"
check "list omits the bare dir and legacy worktree" not grep -qE '\.bare|legacy' <<<"$out"
out="$(cd "$B/.bare" && "$SCRIPT" prune 2>&1)"; rc=$?
check "prune succeeds" [ $rc -eq 0 ]
check "prune removes the free slot" [ ! -e "$(bslot 01)" ]
check "prune keeps the busy slot" [ -d "$(bslot 00)" ]
check "prune keeps the legacy worktree, saying why" grep -q "Kept $B/legacy: PR NONE" <<<"$out"
check "prune keeps the base branch's worktree, saying why" grep -q "Kept $B/master: base branch" <<<"$out"
check "prune keeps the base branch" git -C "$B/.bare" rev-parse -q --verify refs/heads/master
check "prune never mentions the bare dir" not grep -q '\.bare' <<<"$out"
check "prune lists the stray branch" grep -q '^  stray$' <<<"$out"
check "prune leaves the default branch unlisted" not grep -q '^  master$' <<<"$out"

echo "== a bare primary named <repo>.git names slots <repo>-wt-NN"
git clone -q --bare "$M/origin.git" "$M/dev/foo.git" 2>/dev/null
git -C "$M/dev/foo.git" config remote.origin.fetch '+refs/heads/*:refs/remotes/origin/*'
git -C "$M/dev/foo.git" fetch -q origin
out="$(cd "$M/dev/foo.git" && "$SCRIPT" take feat/a 2>/dev/null)"; rc=$?
check "take succeeds" [ $rc -eq 0 ]
check "slot named foo-wt-00" [ "$(tail -n1 <<<"$out")" = "$M/dev/foo-wt-00" ]

echo
if [ $fails -eq 0 ]; then echo "ALL PASSED"; rm -rf "${universes[@]}"; else echo "$fails FAILED (kept ${universes[*]})"; exit 1; fi
