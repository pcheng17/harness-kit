#!/bin/bash
# Claude Code status line: git | model · effort | context | rate limits, or cost when there are none.
# Reads session JSON on stdin and prints one line. Runs under macOS bash 3.2.

if ! command -v jq >/dev/null 2>&1; then
  echo "jq not found"
  exit 0
fi

SEP=" | "
DOT=" · "
BRANCH_ICON=$'\xef\x90\x99' # U+F419, Nerd Font git branch

# One jq process. Each field is exactly one line: wrong types and missing values
# become "" and control characters become spaces, so later reads stay aligned.
{
  IFS= read -r cwd
  IFS= read -r model
  IFS= read -r effort
  IFS= read -r used_pct
  IFS= read -r five_hour
  IFS= read -r seven_day
  IFS= read -r five_hour_reset
  IFS= read -r seven_day_reset
  IFS= read -r cost_cents
} <<FIELDS
$(jq -r '
  def f(p): ((try p catch null) // "") | tostring | gsub("[[:cntrl:]]"; " ");
  f((try .workspace.current_dir catch null) // .cwd),
  f(.model.display_name),
  f(.effort.level),
  f(.context_window.used_percentage),
  f(.rate_limits.five_hour.used_percentage | numbers | floor),
  f(.rate_limits.seven_day.used_percentage | numbers | floor),
  f(.rate_limits.five_hour.resets_at | numbers | floor),
  f(.rate_limits.seven_day.resets_at | numbers | floor),
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
    git_seg="${BRANCH_ICON} @${oid:0:8}"
  else
    [ "${#branch}" -gt 32 ] && branch="${branch:0:12}…${branch: -12}"
    git_seg="${BRANCH_ICON} ${branch}"
  fi

  ahead=0; behind=0
  if [ -n "$ab" ]; then
    ahead="${ab%% *}"; ahead="${ahead#+}"
    behind="${ab##* }"; behind="${behind#-}"
  fi
  [ "$behind" -gt 0 ] 2>/dev/null && git_seg="${git_seg} ⇣${behind}"
  if [ "$ahead" -gt 0 ] 2>/dev/null; then
    [ "$behind" -gt 0 ] 2>/dev/null || git_seg="${git_seg} "
    git_seg="${git_seg}⇡${ahead}"
  fi
  [ "$conflicts" -gt 0 ] && git_seg="${git_seg} ~${conflicts}"
  [ "$staged" -gt 0 ] && git_seg="${git_seg} +${staged}"
  [ "$unstaged" -gt 0 ] && git_seg="${git_seg} !${unstaged}"
  [ "$untracked" -gt 0 ] && git_seg="${git_seg} ?${untracked}"
fi

model_seg=""
if [ -n "$model" ]; then
  if [ -n "$effort" ]; then
    model_seg="${model}${DOT}${effort}"
  else
    model_seg="$model"
  fi
fi

pct="${used_pct%%.*}"
case "$pct" in '' | *[!0-9]*) pct=0 ;; esac
ctx_seg="${pct}% context used"

# Sets $remaining to the time left until the epoch-seconds timestamp $1, or "" if it
# is missing, malformed, or already past.
format_remaining() {
  remaining=""
  case "$1" in '' | *[!0-9]*) return ;; esac
  local secs=$(($1 - now))
  [ "$secs" -gt 0 ] || return
  local days=$((secs / 86400)) hours=$((secs % 86400 / 3600)) mins=$((secs % 3600 / 60))
  if [ "$days" -gt 0 ]; then remaining="${days}d ${hours}h"
  elif [ "$hours" -gt 0 ]; then remaining="${hours}h ${mins}m"
  elif [ "$mins" -gt 0 ]; then remaining="${mins}m"
  else remaining="<1m"; fi
}

now=$(date +%s)
limits_seg=""
for window in "5h:$five_hour:$five_hour_reset" "7d:$seven_day:$seven_day_reset"; do
  label="${window%%:*}"; rest="${window#*:}"
  value="${rest%%:*}"; reset="${rest#*:}"
  case "$value" in '' | *[!0-9]*) continue ;; esac
  format_remaining "$reset"
  entry="${label} ${value}%"
  [ -n "$remaining" ] && entry="${entry} (${remaining})"
  if [ -z "$limits_seg" ]; then limits_seg="$entry"; else limits_seg="${limits_seg}${DOT}${entry}"; fi
done

# Subscribers see their limits; without them (API billing) show session cost instead.
cost_seg=""
if [ -z "$limits_seg" ]; then
  case "$cost_cents" in
    '' | *[!0-9]*) ;;
    *)
      cents=$((cost_cents % 100))
      [ "$cents" -lt 10 ] && cents="0${cents}"
      cost_seg="\$$((cost_cents / 100)).${cents}"
      ;;
  esac
fi

out=""
for seg in "$git_seg" "$model_seg" "$ctx_seg" "$limits_seg" "$cost_seg"; do
  [ -n "$seg" ] || continue
  if [ -z "$out" ]; then out="$seg"; else out="${out}${SEP}${seg}"; fi
done
printf '%s\n' "$out"
