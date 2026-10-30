#!/bin/bash
# Claude Code status line: git | model · effort | context | cost.
# Reads session JSON on stdin and prints one line. Runs under macOS bash 3.2.

if ! command -v jq >/dev/null 2>&1; then
  echo "jq not found"
  exit 0
fi

ESC=$'\033'
RST="${ESC}[0m"
SEP="${ESC}[90m | ${RST}"
DOT="${ESC}[90m · ${RST}"
GIT_GREEN="${ESC}[38;5;76m"
GIT_YELLOW="${ESC}[38;5;178m"
GIT_BLUE="${ESC}[38;5;39m"
GIT_RED="${ESC}[38;5;196m"
MAGENTA="${ESC}[35m"
GREEN="${ESC}[32m"
YELLOW="${ESC}[33m"
RED="${ESC}[31m"
ORANGE="${ESC}[38;5;214m"
BRANCH_ICON=$'\xef\x90\x99' # U+F419, Nerd Font git branch

# One jq process. Each field is exactly one line: wrong types and missing values
# become "" and control characters become spaces, so later reads stay aligned.
{
  IFS= read -r cwd
  IFS= read -r model
  IFS= read -r effort
  IFS= read -r used_pct
  IFS= read -r cost_cents
} <<FIELDS
$(jq -r '
  def f(p): ((try p catch null) // "") | tostring | gsub("[[:cntrl:]]"; " ");
  f((try .workspace.current_dir catch null) // .cwd),
  f(.model.display_name),
  f(.effort.level),
  f(.context_window.used_percentage),
  f(.cost.total_cost_usd | numbers | . * 100 | round)
' 2>/dev/null)
FIELDS

git_seg=""
git_status=$(git -C "${cwd:-$PWD}" --no-optional-locks status --porcelain=v2 --branch 2>/dev/null) || git_status=""
if [ -n "$git_status" ]; then
  oid=""; branch=""; ab=""
  staged=0; unstaged=0; untracked=0; conflicts=0
  while IFS= read -r line; do
    case "$line" in
      '# branch.oid '*) oid="${line#\# branch.oid }" ;;
      '# branch.head '*) branch="${line#\# branch.head }" ;;
      '# branch.ab '*) ab="${line#\# branch.ab }" ;;
      '1 '* | '2 '*)
        [ "${line:2:1}" != "." ] && staged=$((staged + 1))
        [ "${line:3:1}" != "." ] && unstaged=$((unstaged + 1))
        ;;
      'u '*) conflicts=$((conflicts + 1)) ;;
      '? '*) untracked=$((untracked + 1)) ;;
    esac
  done <<GIT_STATUS
$git_status
GIT_STATUS

  if [ "$branch" = "(detached)" ]; then
    git_seg="${GIT_GREEN}@${oid:0:8}"
  else
    [ "${#branch}" -gt 32 ] && branch="${branch:0:12}…${branch: -12}"
    git_seg="${GIT_GREEN}${BRANCH_ICON} ${branch}"
  fi

  ahead=0; behind=0
  if [ -n "$ab" ]; then
    ahead="${ab%% *}"; ahead="${ahead#+}"
    behind="${ab##* }"; behind="${behind#-}"
  fi
  [ "$behind" -gt 0 ] 2>/dev/null && git_seg="${git_seg} ${GIT_GREEN}⇣${behind}"
  if [ "$ahead" -gt 0 ] 2>/dev/null; then
    [ "$behind" -gt 0 ] 2>/dev/null || git_seg="${git_seg} "
    git_seg="${git_seg}${GIT_GREEN}⇡${ahead}"
  fi
  [ "$conflicts" -gt 0 ] && git_seg="${git_seg} ${GIT_RED}~${conflicts}"
  [ "$staged" -gt 0 ] && git_seg="${git_seg} ${GIT_YELLOW}+${staged}"
  [ "$unstaged" -gt 0 ] && git_seg="${git_seg} ${GIT_YELLOW}!${unstaged}"
  [ "$untracked" -gt 0 ] && git_seg="${git_seg} ${GIT_BLUE}?${untracked}"
  git_seg="${git_seg}${RST}"
fi

model_seg=""
if [ -n "$model" ]; then
  if [ -n "$effort" ]; then
    model_seg="${MAGENTA}${model}${DOT}${MAGENTA}${effort}${RST}"
  else
    model_seg="${MAGENTA}${model}${RST}"
  fi
fi

pct="${used_pct%%.*}"
case "$pct" in '' | *[!0-9]*) pct=0 ;; esac
if [ "$pct" -ge 80 ]; then
  pct_color="$RED"
elif [ "$pct" -ge 50 ]; then
  pct_color="$YELLOW"
else
  pct_color="$GREEN"
fi
ctx_seg="${pct_color}${pct}%${RST} context used"

cost_seg=""
case "$cost_cents" in
  '' | *[!0-9]*) ;;
  *)
    cents=$((cost_cents % 100))
    [ "$cents" -lt 10 ] && cents="0${cents}"
    cost_seg="${ORANGE}\$$((cost_cents / 100)).${cents}${RST}"
    ;;
esac

out=""
for seg in "$git_seg" "$model_seg" "$ctx_seg" "$cost_seg"; do
  [ -n "$seg" ] || continue
  if [ -z "$out" ]; then out="$seg"; else out="${out}${SEP}${seg}"; fi
done
printf '%s\n' "$out"
