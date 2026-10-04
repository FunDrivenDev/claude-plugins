#!/usr/bin/env bash
# Claude Code status line — context budget first.
#
# Reads the status-line JSON payload on stdin (schema: Claude Code >= 2.1.x) and
# prints an ANSI-coloured line, then one line per plugin segment (section 7).
# The token counter is scored against the
# auto-compact trigger rather than the model's real context window: compaction,
# not the technical ceiling, is what actually ends the session's memory. The
# trigger sits a reserve below autoCompactWindow: 624 auto-compactions under a
# 175K window fired at a median of 143K, and the docs put the default 1M window's
# trigger at ~967K.
#
# Tunables (env):
#   CC_TOKEN_LIMIT   auto-compact window (default: settings.autoCompactWindow, else 200000)
#   CC_TOKEN_RESERVE tokens below the window where compaction fires (default 33000)
#   CC_TOKEN_WARN    green -> yellow boundary, % of the limit     (default 50)
#   CC_TOKEN_DANGER  yellow -> orange boundary, % of the limit    (default 75)
#   CC_TOKEN_ALERT   orange -> red boundary, % of the limit       (default 90)
#   CC_STATUS_GIT_DIRTY  set to 0 to skip the dirty-tree check on huge repos
#   CC_QUOTA_BAR     cells in each quota bar, 0 to hide the bars      (default 10)
#   CC_PACE_MIN      % of a window that must elapse before a projection is shown (default 10)
# A value that is not a plain integer, or thresholds out of order, fall back to
# the default and are named in a leading "⚠ ignored:" segment.
#   CC_STATUS_SEGMENTS   set to 0 to skip the plugin segments (section 7)

set -uo pipefail

CLAUDE_HOME=${CLAUDE_CONFIG_DIR:-$HOME/.claude}

# Names of the settings that were ignored, shown as the first segment.
ignored=""

# int VAR NAME DEFAULT: VAR = $NAME when it is a plain integer, else DEFAULT.
# A set but unusable value is also recorded in $ignored. Tunables reach
# $((...)), where a stray word would abort the script under set -u; the length
# cap keeps them clear of 64-bit overflow.
int() {
  local v=${!2:-}
  case $v in
    '')                     printf -v "$1" '%s' "$3" ;;
    *[!0-9]*|?????????????*) printf -v "$1" '%s' "$3"; ignored="$ignored $2" ;;
    *)                      printf -v "$1" '%d' "$(( 10#$v ))" ;;
  esac
}

int GIT_DIRTY   CC_STATUS_GIT_DIRTY 1
int QUOTA_BAR   CC_QUOTA_BAR        10
int PACE_MIN    CC_PACE_MIN         10
int RESERVE     CC_TOKEN_RESERVE    33000
int WARN_PCT    CC_TOKEN_WARN       50
int DANGER_PCT  CC_TOKEN_DANGER     75
int ALERT_PCT   CC_TOKEN_ALERT      90
int ENV_LIMIT   CC_TOKEN_LIMIT      ""
int SEGMENTS    CC_STATUS_SEGMENTS  1

if (( WARN_PCT > DANGER_PCT || DANGER_PCT > ALERT_PCT )); then
  ignored="$ignored CC_TOKEN_WARN CC_TOKEN_DANGER CC_TOKEN_ALERT"
  WARN_PCT=50 DANGER_PCT=75 ALERT_PCT=90
fi

# Bold + bright 256-colour: the host wraps our output in Ink's dimColor, so
# faint codes wash out entirely.
GRAY=$'\033[1;38;5;245m'
GREEN=$'\033[1;38;5;82m'
YELLOW=$'\033[1;38;5;226m'
ORANGE=$'\033[1;38;5;214m'
RED=$'\033[1;38;5;196m'
ALERT=$'\033[1;97;48;5;196m'
DIM=$'\033[38;5;240m'
TEXT=$'\033[38;5;250m'
R=$'\033[0m'

# Field separator for the jq -> read handoff. Passed in as a jq --arg rather
# than written inline: tab is IFS-whitespace, so `read` would collapse
# consecutive empty fields and shift every later value left.
US=$'\037'

# A version-manager shim (mise, asdf) re-resolves the tool on every call, which
# costs several times jq's own run; take the first real jq on PATH instead.
JQ=jq
IFS=:; set -f
for d in $PATH; do
  case $d in */shims) continue ;; esac
  if [ -f "$d/jq" ] && [ -x "$d/jq" ]; then JQ=$d/jq; break; fi
done
IFS=$' \t\n'; set +f

# The payload is kept for the plugin segments, which read it too.
payload=$(cat)

# One jq call reads the payload, autoCompactWindow from the settings
# and the clock, integers pre-rounded. Both documents are parsed leniently: a
# malformed file or a field of an unexpected type falls back to that field's
# default instead of failing the whole call. Control characters are stripped
# from strings so none can carry the separator or a newline into `read`. The
# trailing "." sentinel stops `read` from dropping empty trailing fields.
settings=()
[ -z "$ENV_LIMIT" ] && [ -r "$CLAUDE_HOME/settings.json" ] &&
  settings=(--rawfile s "$CLAUDE_HOME/settings.json")
# ${a[@]+...}: bash < 4.4 (macOS /bin/bash) treats an empty array as unbound under set -u.
IFS=$US read -r NOW ACW TOK HAS MINS MODEL EFFORT FAST THINK H5 R5 D7 R7 CWD WTREE PRNUM PRSTATE PC_ON PC_WARM PC_EXP PC_TTL PC_RECACHE _SENTINEL < <(
  "$JQ" -Rsr --arg us "$US" ${settings[@]+"${settings[@]}"} '
  def doc: (fromjson? | objects) // {};
  def v(p): try getpath(p) catch null;
  def int: numbers | select(. > -1e15 and . < 1e15) | floor;
  def n(p; d): v(p) | int // d;
  def s(p): v(p) // "" | tostring | explode | map(select(. >= 32)) | implode;
  ($ARGS.named.s // "" | doc | .autoCompactWindow
    | if . == null then ""
      else (if type == "string" then tonumber? else . end | int) // "!" end) as $acw
  | doc
  | [ (now | floor)
    , $acw
    , n(["context_window","total_input_tokens"]; 0)
    , (if v(["context_window","current_usage"]) == null then 0 else 1 end)
    , (v(["cost","total_duration_ms"]) | (int / 60000 | floor) // 0)
    , s(["model","display_name"])
    , s(["effort","level"])
    , (if v(["fast_mode"]) then 1 else 0 end)
    , (if v(["thinking","enabled"]) == false then 0 else 1 end)
    , n(["rate_limits","five_hour","used_percentage"]; -1)
    , n(["rate_limits","five_hour","resets_at"]; 0)
    , n(["rate_limits","seven_day","used_percentage"]; -1)
    , n(["rate_limits","seven_day","resets_at"]; 0)
    , s(["cwd"])
    , s(["workspace","git_worktree"])
    , s(["pr","number"])
    , s(["pr","review_state"])
    , (if v(["prompt_cache","caching_observed"]) then 1 else 0 end)
    , (if v(["prompt_cache","warm"]) then 1 else 0 end)
    , n(["prompt_cache","expires_at"]; 0)
    , s(["prompt_cache","ttl"])
    , n(["prompt_cache","recache_tokens_if_cold"]; 0)
    , "." ] | map(tostring) | join($us)' <<<"$payload" 2>/dev/null)

jq_err=""
if [ "${_SENTINEL:-}" != "." ]; then
  # Every field is empty: defaults below, and a segment saying why.
  if command -v "$JQ" >/dev/null; then jq_err="jq failed (1.6+ needed)"; else jq_err="jq not found"; fi
fi

[ "${ACW:-}" = "!" ] && ignored="$ignored autoCompactWindow" && ACW=""
if   [ -n "$ENV_LIMIT" ];  then WIN=$ENV_LIMIT WIN_SRC=CC_TOKEN_LIMIT
elif [ -n "${ACW:-}" ];    then WIN=$ACW       WIN_SRC=autoCompactWindow
else                            WIN=200000     WIN_SRC="default window"
fi
LIMIT=$(( WIN - RESERVE ))
WARN=$((   LIMIT * WARN_PCT   / 100 ))
DANGER=$(( LIMIT * DANGER_PCT / 100 ))
ALERT_AT=$(( LIMIT * ALERT_PCT / 100 ))

: "${NOW:=0}"
: "${TOK:=0}" "${HAS:=0}" "${MINS:=0}" "${MODEL:=}" "${EFFORT:=}"
: "${FAST:=0}" "${THINK:=1}" "${H5:=-1}" "${R5:=0}" "${D7:=-1}" "${R7:=0}" "${CWD:=}"
: "${WTREE:=}" "${PRNUM:=}" "${PRSTATE:=}"
: "${PC_ON:=0}" "${PC_WARM:=0}" "${PC_EXP:=0}" "${PC_TTL:=}" "${PC_RECACHE:=0}"

# --- helpers ---------------------------------------------------------------

# The helpers set a variable rather than print, so callers need no $(...)
# subshell: forks, not arithmetic, are what cost a status line its time.

# 78234 -> K="78.2k", 934 -> K="934".
kfmt() {
  if (( $1 >= 1000 )); then
    printf -v K '%d.%dk' $(( $1 / 1000 )) $(( ($1 % 1000) / 100 ))
  else
    K=$1
  fi
}

COL=$GREEN

# 42 -> D="42m", 194 -> D="3h14m", 2760 -> D="1d22h". Arg in minutes.
dur() {
  local m=$1
  if   (( m >= 1440 )); then printf -v D '%dd%02dh' $(( m / 1440 )) $(( m % 1440 / 60 ))
  elif (( m >= 60 ));   then printf -v D '%dh%02dm' $(( m / 60 )) $(( m % 60 ))
  else                       D="${m}m"
  fi
}

line=""
add() {
  [ -z "$1" ] && return 0
  if [ -n "$line" ]; then line="$line ${DIM}│${R} $1"; else line="$1"; fi
}

# --- 0. configuration problems (leftmost: never truncated) -----------------

[ -n "$ignored" ] && add "${ORANGE}⚠ ignored:${ignored}${R}"
# Without the payload every other segment would show defaults, not data.
if [ -n "$jq_err" ]; then
  add "${RED}⚠ ${jq_err}${R}"
  printf '%s' "$line"
  exit 0
fi

# --- 1. duration -----------------------------------------------------------

if (( MINS >= 60 )); then
  printf -v elapsed '%dh%02dm' $(( MINS / 60 )) $(( MINS % 60 ))
else
  elapsed="${MINS}m"
fi
head="${TEXT}⌛${elapsed}${R}"   # shares a segment with the cache countdown

# --- 2. prompt cache countdown ----------------------------------------------
#
# Time until the cached conversation prefix leaves its TTL. Past that, the next
# message re-processes the whole conversation at full input price instead of
# the cache-read discount, so an expired cache shows how many tokens it will cost.
# Coloured by the share of the TTL left. Absent until the first API response,
# and when the provider reports no caching.

if (( PC_ON == 1 )); then
  case "$PC_TTL" in 5m) ttl=300 ;; *) ttl=3600 ;; esac
  if (( PC_WARM == 1 && PC_EXP > NOW )); then
    left=$(( PC_EXP - NOW ))
    if   (( left < 60 ));           then cl="<1m"; else dur $(( left / 60 )); cl=$D; fi
    if   (( left * 2 >= ttl ));     then COL=$GREEN
    elif (( left * 5 >= ttl ));     then COL=$YELLOW
    else                                 COL=$ORANGE
    fi
    head="$head ${TEXT}TTL${R} ${COL}${cl}${R}"
  else
    head="$head ${RED}EXP${R}"
    (( PC_RECACHE > 0 )) && kfmt "$PC_RECACHE" && head="$head ${TEXT}🔄${K}${R}"
  fi
fi
add "$head"

# --- 3. model / effort / modes ---------------------------------------------

mdl=""
[ -n "$MODEL" ]  && mdl="${TEXT}${MODEL}${R}"
# effort as a position on the scale low, medium, high, xhigh, max: high -> 3/5,
# in the colour /effort gives that level (Claude Code dark theme; max's animated
# rainbow becomes one rainbow colour per character)
case "$EFFORT" in
  low)    eff=$'\033[1;38;2;255;193;7m1/5' ;;
  medium) eff=$'\033[1;38;2;78;186;101m2/5' ;;
  high)   eff=$'\033[1;38;2;177;185;249m3/5' ;;
  xhigh)  eff=$'\033[1;38;2;175;135;255m4/5' ;;
  max)    eff=$'\033[1;38;2;235;95;87m5\033[1;38;2;250;195;95m/\033[1;38;2;130;170;220m5' ;;
  *)      eff="${TEXT}${EFFORT}" ;;
esac
[ -n "$EFFORT" ] && mdl="${mdl:+$mdl }${eff}${R}"
(( FAST == 1 ))  && mdl="${mdl:+$mdl }${ORANGE}⚡${R}"
(( THINK == 0 )) && mdl="${mdl:+$mdl }${ORANGE}¬think${R}"
add "$mdl"

# --- 4. context budget (near the left: truncation eats the right side) -----

if (( LIMIT % 1000 == 0 )); then lim_lbl="$(( LIMIT / 1000 ))k"; else kfmt "$LIMIT"; lim_lbl=$K; fi

if (( LIMIT <= 0 )); then
  add "${RED}⚠ ${WIN_SRC} ${WIN} ≤ CC_TOKEN_RESERVE ${RESERVE}${R}"
elif (( HAS == 0 )); then
  add "${GRAY}0/${lim_lbl}${R}"
else
  pct=$(( TOK * 100 / LIMIT ))
  kfmt "$TOK"
  body="${K}/${lim_lbl} ${pct}%"
  if   (( TOK <= WARN ));     then add "${GREEN}${body}${R}"
  elif (( TOK <= DANGER ));   then add "${YELLOW}${body}${R}"
  elif (( TOK <= ALERT_AT )); then add "${ORANGE}${body}${R}"
  elif (( TOK < LIMIT ));     then add "${RED}${body}${R}"
  else                            add "${ALERT} ${body} ⚠ COMPACTING ${R}"
  fi
fi

# --- 5. quota windows: usage against elapsed time --------------------------
#
# Each window reads as: bar, % used, verdict, time until reset.
#
#   5h █│░░░░░░░░░  12% ok →34% 🔄3h14m
#   7d ██████│█░░░  71% out 1d21h 🔄2d07h
#
# The bar fills with usage; the │ tick marks where even spending would put you
# by now (the share of the window elapsed). Fill left of the tick is green,
# fill past it is ahead of pace and takes the verdict's colour. The verdict
# extrapolates the average burn rate to the reset:
#   ok →N%     lands at N% (under 90%)
#   tight →N%  lands at 90-100%
#   out D      hits the limit in D, before the reset
#   max        limit reached
# Absent until PACE_MIN % of the window has elapsed. Opus has no model-scoped
# bucket; it bills the aggregate windows.

# quota LABEL USED% RESETS_AT WINDOW_SECONDS -> sets Q
quota() {
  local lbl=$1 used=$2 reset=$3 win=$4
  Q=""
  (( used >= 0 )) || return 0

  local left=-1 el=-1
  if (( reset > NOW )); then
    left=$(( reset - NOW ))
    (( left > win )) && left=$win
    el=$(( (win - left) * 1000 / win ))       # per-mille of the window elapsed
  fi

  # verdict, and the colour it lends to the overshoot and the % used
  local verdict="" vcol=$GREEN
  if (( used >= 100 )); then
    vcol=$RED; verdict="${ALERT} max ${R}"
  elif (( el > 0 && el >= PACE_MIN * 10 )); then
    local proj=0
    (( used > 0 )) && proj=$(( (used * 1000 + el / 2) / el ))
    if (( proj > 100 )); then
      # minutes until 100% at the current rate: (100-used) / (used / elapsed)
      local dry=$(( (100 - used) * (win - left) / used / 60 ))
      dur "$dry"
      vcol=$RED;    verdict="${ALERT} out ${D} ${R}"
    elif (( proj >= 90 )); then
      vcol=$YELLOW; verdict="${YELLOW}tight →${proj}%${R}"
    else
      verdict="${GREEN}ok →${proj}%${R}"
    fi
  fi
  local body
  printf -v body '%s%3d%%%s' "$vcol" "$used" "$R"

  # bar: n cells plus the pace tick (a blank when the window is unknown)
  local bar=""
  if (( QUOTA_BAR > 0 )); then
    local n=$QUOTA_BAR i u t=-1
    u=$(( (used * n + 50) / 100 )); (( u > n )) && u=$n
    (( el >= 0 )) && t=$(( (el * n + 500) / 1000 ))
    for (( i = 0; i <= n; i++ )); do
      if (( i == t )); then bar+="${TEXT}│"
      elif (( i == n && t < 0 )); then bar+=" "
      fi
      (( i == n )) && break
      if   (( i < u && (t < 0 || i < t) )); then bar+="${GREEN}█"
      elif (( i < u ));                      then bar+="${vcol}█"
      else                                        bar+="${DIM}░"
      fi
    done
    bar+="$R "
  fi

  local rs=""
  (( left >= 0 )) && dur $(( left / 60 )) && rs="🔄${TEXT}${D}${R}"

  Q="${TEXT}${lbl}${R} ${bar}${body}${verdict:+ $verdict}${rs:+ $rs}"
}

quota 5h "$H5" "$R5" 18000;  add "$Q"
quota 7d "$D7" "$R7" 604800; add "$Q"

# --- 6. git / worktree / PR ------------------------------------------------

# One `git status` gives both the branch and the dirty flag. -uno leaves
# untracked files out, and a branch with no commit yet counts as dirty.
# --no-ahead-behind skips the commit walk to the upstream, whose count is not
# shown. Detached HEAD shows no segment.
git_seg=""
if [ -n "$CWD" ]; then
  br="" dirty=""
  if (( GIT_DIRTY == 1 )); then
    while IFS= read -r l; do
      case "$l" in
        "# branch.head (detached)") ;;
        "# branch.head "*)          br=${l#"# branch.head "} ;;
        "# branch.oid (initial)")   dirty="*" ;;
        "#"*)                       ;;
        *)                          dirty="*"; break ;;
      esac
    done < <(git -C "$CWD" --no-optional-locks status --porcelain=v2 --branch --no-ahead-behind -uno 2>/dev/null)
  else
    br=$(git -C "$CWD" --no-optional-locks branch --show-current 2>/dev/null)
  fi
  if [ -n "$br" ]; then
    git_seg="${TEXT}⎇ ${br}${R}${ORANGE}${dirty}${R}"
    [ -n "$WTREE" ] && git_seg="$git_seg ${TEXT}[${WTREE}]${R}"
    if [ -n "$PRNUM" ]; then
      case "$PRSTATE" in
        APPROVED|approved)                 mark="${GREEN}✓${R}" ;;
        CHANGES_REQUESTED|changes_requested) mark="${RED}✗${R}" ;;
        *)                                 mark="" ;;
      esac
      git_seg="$git_seg ${TEXT}#${PRNUM}${R}${mark}"
    fi
  fi
fi
add "$git_seg"

printf '%s' "$line"

# --- 7. plugin segments (one line each) --------------------------------------
#
# An installed plugin that ships an executable `statusline-segment` at its root
# gets a line of its own: it reads the same payload on stdin and prints one line,
# or nothing. A segment prints nothing where its plugin is disabled, for the
# status line cannot tell. Each runs on every refresh, so it must be quick.

if (( SEGMENTS == 1 )) && [ -r "$CLAUDE_HOME/plugins/installed_plugins.json" ]; then
  while IFS= read -r dir; do
    [ -n "$dir" ] && [ -f "$dir/statusline-segment" ] && [ -x "$dir/statusline-segment" ] || continue
    seg=$("$dir/statusline-segment" <<<"$payload" 2>/dev/null) || continue
    seg=${seg%%$'\n'*}
    [ -n "$seg" ] && printf '\n%s' "$seg"
  done < <("$JQ" -r '.plugins // {} | to_entries[] | .value[0].installPath // empty' \
             "$CLAUDE_HOME/plugins/installed_plugins.json" 2>/dev/null)
fi
exit 0
