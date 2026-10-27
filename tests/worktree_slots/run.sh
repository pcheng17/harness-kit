#!/usr/bin/env bash
# Black-box tests for the worktree-slots skill's wt.sh against throwaway repos and a stub gh.
# Usage: run.sh [path-to-wt.sh]   (default: the skill's wt.sh in this checkout)
# Each scenario builds its universe under $TMPDIR; all are removed when every check passes.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE="$(realpath "${1:-$HERE/../../content/skills/worktree-slots/wt.sh}")"
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
check "header is column-aligned" bash -c 'h=$(head -n1 <<<"$1"); r=$(sed -n 2p <<<"$1"); [ "$(awk "{print index(\$0, \"PATH\")}" <<<"$h")" -eq "$(awk "{print index(\$0, \"/\")}" <<<"$r")" ]' _ "$out"

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

echo
if [ $fails -eq 0 ]; then echo "ALL PASSED"; rm -rf "${universes[@]}"; else echo "$fails FAILED (kept ${universes[*]})"; exit 1; fi
