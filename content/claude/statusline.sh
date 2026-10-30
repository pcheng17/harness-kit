#!/bin/bash
# Claude Code status line: cwd git | model · effort | context | rate limits, or cost when there are none.
# Reads session JSON on stdin and prints one line. Runs under macOS bash 3.2.

if ! command -v jq >/dev/null 2>&1; then
  echo "jq not found"
  exit 0
fi

ESC=$'\033'
RST="${ESC}[0m"
GRAY="${ESC}[90m"
SEP="${GRAY} | ${RST}"
DOT="${GRAY} · ${RST}"
GIT_GREEN="${ESC}[38;5;76m"
GIT_YELLOW="${ESC}[38;5;178m"
GIT_BLUE="${ESC}[38;5;39m"
GIT_RED="${ESC}[38;5;196m"
DIR_BLUE="${ESC}[0;38;5;31m"
DIR_SHORT="${ESC}[0;38;5;103m"
DIR_ANCHOR="${ESC}[0;1;38;5;39m"
# A directory holding any of these is highlighted as an anchor (mirrors the p10k anchor list).
DIR_MARKERS=".bzr .citc .git .hg .node-version .python-version .go-version .ruby-version
  .lua-version .java-version .perl-version .php-version .tool-versions .mise.toml
  .shorten_folder_marker .svn .terraform CVS Cargo.toml composer.json go.mod package.json stack.yaml"

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

# Sets $short to the shortest prefix of directory $2 that no other directory in $1
# starts with, like p10k's truncate_to_unique. Hidden siblings only compete with
# hidden names, matching glob semantics.
unique_prefix() {
  local parent="$1" name="$2" len=1 sib clash
  local -a sibs
  sibs=()
  if [ "${name:0:1}" = "." ]; then
    for sib in "$parent"/.*/; do sibs+=("$sib"); done
  else
    for sib in "$parent"/*/; do sibs+=("$sib"); done
  fi
  while [ "$len" -lt "${#name}" ]; do
    clash=0
    for sib in "${sibs[@]}"; do
      sib="${sib%/}"; sib="${sib##*/}"
      case "$sib" in . | .. | "$name") continue ;; esac
      [ -d "$parent/$sib" ] && [ "${sib:0:len}" = "${name:0:len}" ] && { clash=1; break; }
    done
    [ "$clash" -eq 0 ] && break
    len=$((len + 1))
  done
  short="${name:0:len}"
}

# Sets $dir_seg like the p10k prompt: ~ for home, the first, last, and
# marker-holding directories bold blue, the rest muted and truncated to unique prefixes.
build_dir_seg() {
  local path="$1" real="" out="" comp marker anchor i n short
  local raw parts
  if [ -n "$HOME" ] && { [ "$path" = "$HOME" ] || [ "${path#"$HOME"/}" != "$path" ]; }; then
    out="${DIR_ANCHOR}~"; real="$HOME"; path="${path#"$HOME"}"
  fi
  IFS=/ read -r -a raw <<<"$path"
  parts=()
  for comp in "${raw[@]}"; do
    [ -n "$comp" ] && parts+=("$comp")
  done
  n=${#parts[@]}
  [ "$n" -eq 0 ] && [ -z "$out" ] && out="${DIR_BLUE}/"
  i=0
  while [ "$i" -lt "$n" ]; do
    comp="${parts[$i]}"
    anchor=0
    [ "$i" -eq $((n - 1)) ] && anchor=1
    [ "$i" -eq 0 ] && [ -z "$real" ] && anchor=1
    if [ "$anchor" -eq 0 ]; then
      for marker in $DIR_MARKERS; do
        [ -e "$real/$comp/$marker" ] && { anchor=1; break; }
      done
    fi
    out="${out}${DIR_BLUE}/"
    if [ "$anchor" -eq 1 ]; then
      out="${out}${DIR_ANCHOR}${comp}"
    else
      unique_prefix "${real:-/}" "$comp"
      out="${out}${DIR_SHORT}${short}"
    fi
    real="$real/$comp"
    i=$((i + 1))
  done
  dir_seg="${out}${RST}"
}

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
    git_seg="${GIT_GREEN}${branch}"
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

dir_seg=""
[ -n "$cwd" ] && build_dir_seg "$cwd"
loc_seg="$dir_seg"
if [ -n "$git_seg" ]; then
  if [ -n "$loc_seg" ]; then loc_seg="${loc_seg} ${git_seg}"; else loc_seg="$git_seg"; fi
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
for seg in "$loc_seg" "$model_seg" "$ctx_seg" "$limits_seg" "$cost_seg"; do
  [ -n "$seg" ] || continue
  if [ -z "$out" ]; then out="$seg"; else out="${out}${SEP}${seg}"; fi
done
printf '%s\n' "$out"
