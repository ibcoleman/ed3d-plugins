#!/bin/sh
# jj-preflight.sh — GitHub Copilot CLI `preToolUse` command hook.
#
# Guards a Jujutsu (jj) repository (optionally colocated with git) against
# unsafe direct `git` operations and categorically unsafe shell commands.
# It reads a single JSON object on stdin and always emits an *exact* JSON
# object on stdout:
#
#   {"permissionDecision":"allow","permissionDecisionReason":"..."}
#   {"permissionDecision":"deny","permissionDecisionReason":"..."}
#
# The payload is consumed with jq (object form of toolArgs, or a serialized
# string form such as {"command":"..."}). Reasons use a fixed, generic
# vocabulary and NEVER include secrets, arguments, or user data.
#
# Policy summary (deterministic, conservative — deny-first):
#   - Malformed / missing input  -> deny (no secrets echoed)
#   - Any non-"bash" tool        -> allow (no inspection)
#   - bash command must resolve to only read-only verbs, else deny
#   - Compound (`;` `&&` `||`), command substitution (`$()` `` ` ``),
#     process substitution (`<( ... )` / `>( ... )`), any newline or
#     carriage-return command separator, write redirection, and wrapper
#     invocations (sudo/su/eval/xargs/env/nohup/setsid/timeout/...), `sh -c` /
#     `bash -c` style re-exec, and `command`/`builtin`/`type` re-exec or
#     inspection wrappers are all denied (a standalone `type <name>` no longer
#     passes — it can obscure what is actually run)
#   - `git` mutating/staging ops in a jj-managed repo are denied, including
#     every `git push --force*` form (force is never whitelisted)
#   - `git branch/tag/config/remote` are allowed ONLY as genuinely read-only
#     query forms (branch/tag list/show, config get/list, remote
#     show/get-url/list); every mutating or ambiguous form is denied
#   - jj subcommand families are restricted: `jj op` only log/show/walk,
#     `jj file` only show/list/annotate, `util`/`debug` conservative deny;
#     `jj git remote/clone/init`, `jj git push` (all force/ambiguous-target
#     forms), and other jj git mutating remote forms are denied
#   - In a colocated repo, the git index is inspected read-only: tracked or
#     stageable `.jj` descendants block mutating/staging/push operations
#   - Repository state is verified from the authoritative payload cwd:
#       . repo discovery (walk up for .jj / .git; `.git` may be a gitdir file)
#       . jj metadata via `jj root --ignore-working-copy` (must match root);
#         a failing/mismatched root fails safe (mutations denied)
#       . conflict and bookmark queries via read-only real-jj invocations
#         (`-T description`, not `-T x`); a failed conflict/bookmark query
#         defaults to "no conflict" / "not detached" (exit-status fail-safe)

set -u
# Disable pathname (glob) expansion so the unquoted token loops below
# (`for v in $verbs`, `for w in $rest`, ...) never expand file globs in
# untrusted argument text into additional tokens.
set -f

# ---- Fixed, generic reason vocabulary (no secrets / no user data) ----
R_MALFORMED="jj-preflight: could not parse tool payload"
R_NON_REPO="jj-preflight: no jj or git repository found for command target"
R_GIT_MUTATE="jj-preflight: git mutating/staging operation in a jj-managed repo"
R_UNSAFE_CMD="jj-preflight: command is not a recognized read-only operation"
R_COMPOUND="jj-preflight: compound or wrapped command with unsafe component"
R_CONFLICT="jj-preflight: repository has unresolved conflicts"
R_GIT_OP="jj-preflight: a git operation is in progress"
R_DETACHED="jj-preflight: working-copy commit is detached"
R_METADATA="jj-preflight: could not verify jj metadata/repository state"
R_JJ_TRACKED="jj-preflight: jj internal state is tracked or stageable by git"

# ---- Output helpers (fail-closed: plain printf fallback if jq is absent) ----
emit() {
  decision=$1
  reason=${2:-}
  if command -v jq >/dev/null 2>&1; then
    if [ -n "$reason" ]; then
      jq -nc --arg d "$decision" --arg r "$reason" \
        '{permissionDecision:$d,permissionDecisionReason:$r}'
    else
      jq -nc --arg d "$decision" '{permissionDecision:$d}'
    fi
  else
    if [ -n "$reason" ]; then
      printf '{"permissionDecision":"%s","permissionDecisionReason":"%s"}\n' \
        "$decision" "$reason"
    else
      printf '{"permissionDecision":"%s"}\n' "$decision"
    fi
  fi
  exit 0
}
deny() { emit deny "${1:-$R_MALFORMED}"; }
allow() { emit allow; }

# ---- 1. Read payload + validate top-level shape ----
payload=$(cat)
if ! command -v jq >/dev/null 2>&1; then
  deny "$R_MALFORMED"
fi
printf '%s' "$payload" | jq -e 'type=="object"' >/dev/null 2>&1 || deny "$R_MALFORMED"

cwd=$(printf '%s' "$payload" | jq -r '(.cwd // empty)' 2>/dev/null)
tool=$(printf '%s' "$payload" | jq -r '(.toolName // empty)' 2>/dev/null)
[ -n "$tool" ] || deny "$R_MALFORMED"
[ -n "$cwd" ] || deny "$R_MALFORMED"

# ---- 2. Only the bash tool is in scope; everything else passes uninspected ----
[ "$tool" = "bash" ] || allow

# ---- 3. Extract the command from toolArgs (object OR serialized string) ----
cmd=$(printf '%s' "$payload" | jq -r '
  (.toolArgs | if type=="string" then (try fromjson catch .) else . end) as $o |
  if ($o | type)=="object" then ($o.command // "")
  elif ($o | type)=="array" then ($o | join(" "))
  else "" end' 2>/dev/null)

# Drop a leading `-c ` used by the array form (e.g. ["-c","git status"])
case "$cmd" in
  -c\ *) cmd=${cmd#-c } ;;
  -c) deny "$R_COMPOUND" ;;
esac
# Trim surrounding whitespace
cmd=$(printf '%s' "$cmd" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')
[ -n "$cmd" ] || deny "$R_MALFORMED"

# ---- 4. Lexical / compound / wrapper defenses on the whole command ----
case "$cmd" in
  *'$('* | *'`'*) deny "$R_COMPOUND" ;;          # command substitution
  *'&&'* | *'||'* | *';'*) deny "$R_COMPOUND" ;; # sequential/conditional control
  *'<('* | *'>('*) deny "$R_COMPOUND" ;;         # process substitution
esac
# Any newline acts as a command separator: deny it. (A carriage return is
# likewise a separator and is denied below.) After trailing-whitespace trim a
# remaining "%s\n" means another command was smuggled in.
if [ "$(printf '%s' "$cmd" | wc -l)" -ge 1 ]; then deny "$R_COMPOUND"; fi
# Embedded carriage return can smuggle additional command text.
if printf '%s' "$cmd" | grep -q -F "$(printf '\r')"; then deny "$R_COMPOUND"; fi
case "$cmd" in
  sudo* | su\ * | eval* | xargs* | env\ * | nohup* | setsid* | \
  timeout\ * | nice\ * | stdbuf\ * | script\ * | watch\ * | \
  command\ * | builtin\ * | type\ * | \
  sh\ -c* | bash\ -c* | dash\ -c* | zsh\ -c* | ksh\ -c*)
    deny "$R_COMPOUND" ;;  # wrapper invocations that can escalate / re-exec
esac

# Write-redirection check: any '>' that is not an attached allowed stream/
# DEVNULL form (for example, >/dev/null or 2>&1) is denied.
if printf '%s' "$cmd" | grep -q '>'; then
  rest=$(printf '%s' "$cmd" | sed \
    -e 's/2>&1//g' \
    -e 's#>/dev/null##g' \
    -e 's#1>/dev/null##g' \
    -e 's#2>/dev/null##g' \
    -e 's#>/dev/stderr##g' \
    -e 's#>/dev/stdout##g')
  case "$rest" in
    *'>'*) deny "$R_COMPOUND" ;;
  esac
fi

# ---- 5. Extract command-position verbs (allows read-only pipelines) ----
extract_verbs() {
  printf '%s\n' "$1" | awk '
  {
    n = split($0, seg, "|")
    for (s = 1; s <= n; s++) {
      m = split(seg[s], w, /[ \t]+/)
      for (i = 1; i <= m; i++) {
        t = w[i]
        if (t == "") continue          # leading/trailing space after `|` / blank
        if (t ~ /^[0-9]*>/) continue   # redirect target / 2>&1 etc.
        if (t == "<") continue
        if (t ~ /^>/) continue
        if (t ~ /^[A-Za-z_][A-Za-z0-9_]*=$/) continue  # env assignment
        if (t ~ /^-/) continue         # option flag
        print t
        break
      }
    }
  }'
}

verbs=$(extract_verbs "$cmd")

has_git=0
has_jj=0
cmd_safe=1
for v in $verbs; do
  case "$v" in
    git) has_git=1 ;;
    jj) has_jj=1 ;;
  esac
done
for v in $verbs; do
  case "$v" in
    git | jj) continue ;;
  esac
  case "$v" in
    cat|ls|echo|printf|pwd|cd|which|true|false|head|tail|wc|grep|egrep|fgrep|rg|sort|uniq|cut|tr|fold|fmt|less|more|column|diff|cmp|file|stat|readlink|basename|dirname|realpath|date|jq) ;;
    *) cmd_safe=0 ;;
  esac
done
[ "$cmd_safe" = 1 ] || deny "$R_UNSAFE_CMD"

# Pure read-only (no git/jj): nothing to guard — allow immediately.
[ "$has_git" = 0 ] && [ "$has_jj" = 0 ] && allow

# ---- 5b. Multi-invocation guard ----
# Classification below keys off a segment's first verb (and the FIRST git/jj
# token in the command), so a pipeline that hides a mutating git/jj behind a
# read-only first segment (e.g. `git status | git checkout`,
# `cat | git add`, `jj log | jj git push`) would be misread as read-only. A
# command carrying MORE THAN ONE independent git/jj invocation (one per
# pipeline segment, as reported by extract_verbs) is never classifiable here,
# so deny it outright. A single invocation (`jj git push` is ONE jj command —
# its `git` words are arguments, not a second command) stays classifiable.
ngv=$(printf '%s\n' "$verbs" | awk '$1=="git" { n++ } END { print n+0 }')
njv=$(printf '%s\n' "$verbs" | awk '$1=="jj"  { n++ } END { print n+0 }')
if [ "$((ngv + njv))" -ge 2 ]; then deny "$R_COMPOUND"; fi

# ---- 5c. Argument-position token smuggling guard ----
# A literal `git` or `jj` KEYWORD appearing in an ARGUMENT position of an
# earlier pipeline segment while a command-position git/jj exists later is
# smuggling: e.g. `echo git status | git push` would otherwise let the `git` in
# `echo git status` be misread as the invocation token and classify `git push`
# as if it were `git status`. Such a command is ambiguous and never
# classifiable, so deny it outright. Subcommand arguments where the keyword
# follows the command-position tool in the SAME segment (`jj git push`) are not
# affected — they are classified as the jj `git` subcommand below.
smuggle=$(printf '%s\n' "$cmd" | awk '
  {
    n = split($0, seg, "|")
    posi = 0
    for (s = 1; s <= n; s++) {
      m = split(seg[s], w, /[ \t]+/)
      cmdv = ""
      for (i = 1; i <= m; i++) {
        t = w[i]
        if (t == "") continue
        if (t ~ /^[0-9]*>/) continue
        if (t == "<") continue
        if (t ~ /^>/) continue
        if (t ~ /^[A-Za-z_][A-Za-z0-9_]*=$/) continue
        if (t ~ /^-/) continue
        cmdv = t; break
      }
      if (cmdv == "git" || cmdv == "jj") posi = s
    }
    if (posi == 0) { print 0; exit }
    for (s = 1; s < posi; s++) {
      m = split(seg[s], w, /[ \t]+/)
      for (i = 1; i <= m; i++) {
        if (w[i] == "git" || w[i] == "jj") { print 1; exit }
      }
    }
    print 0
  }')
[ "$smuggle" = "1" ] && deny "$R_COMPOUND"

# ---- 6. Classify git / jj subcommands (read-only vs mutating/staging) ----
# Classification keys off the COMMAND-POSITION git/jj: the first pipeline
# segment whose LEADING verb is git/jj. A bare `git`/`jj` token appearing as an
# ARGUMENT in an earlier segment (argument-position smuggling, e.g.
# `echo git status | git push`, `ls git log | git reset --hard`, or
# `echo jj log | jj op undo`) must NOT be mistaken for the invocation — the real
# mutating op lives in the later command-position segment.
git_sub=$(printf '%s' "$cmd" | awk '
  {
    n = split($0, seg, "|")
    for (s = 1; s <= n; s++) {
      m = split(seg[s], w, /[ \t]+/)
      li = 0
      for (i = 1; i <= m; i++) {
        if (w[i] == "") continue
        if (w[i] ~ /^[0-9]*>/) continue
        if (w[i] == "<") continue
        if (w[i] ~ /^>/) continue
        if (w[i] ~ /^[A-Za-z_][A-Za-z0-9_]*=$/) continue
        li = i; break
      }
      if (li && w[li] == "git" && li+1 <= m) { print w[li+1]; exit }
    }
  }')
git_rest=$(printf '%s' "$cmd" | awk '
  {
    n = split($0, seg, "|")
    for (s = 1; s <= n; s++) {
      m = split(seg[s], w, /[ \t]+/)
      li = 0
      for (i = 1; i <= m; i++) {
        if (w[i] == "") continue
        if (w[i] ~ /^[0-9]*>/) continue
        if (w[i] == "<") continue
        if (w[i] ~ /^>/) continue
        if (w[i] ~ /^[A-Za-z_][A-Za-z0-9_]*=$/) continue
        li = i; break
      }
      if (li && w[li] == "git") {
        for (j = li+2; j <= m; j++) printf "%s ", w[j]
        exit
      }
    }
  }')

# git add broad forms that could sweep up .jj internals.
git_broad_add=0
if [ "$git_sub" = "add" ]; then
  git_broad_add=$(printf '%s' "$git_rest" | awk '
    { for(i=1;i<=NF;i++){ if($i=="."||$i=="-A"||$i=="--all"){ print 1; exit } } print 0 }')
fi

# Subcommand-level read-only classification. Genuinely read-only git
# subcommands (status/log/diff/show/rev-parse/ls-*/describe/help/version) are
# allowed when the repo state is clean; `branch`/`tag`/`config`/`remote` are
# allowed ONLY as read-only query forms (checked per-invocation by
# readonly_git_query); any `git push*` (including every force form) and every
# other subcommand is mutating and maps to R_GIT_MUTATE.

# Return 0 if a git branch/tag/config/remote invocation is a pure read-only
# query, 1 otherwise (any mutating or ambiguous form is treated as read-write).
readonly_git_query() {
  sub=$1
  rest=$2
  has_op=0
  has_name=0
  has_list=0
  has_q=0
  npos=0
  case "$sub" in
    branch)
      for w in $rest; do
        case "$w" in
          -d|-D|-m|-M|-c|-C|-f|--delete|--move|--copy|--force|--set-upstream-to*|--unset-upstream|--edit-description|--create-reflog|--track|--no-track) has_op=1 ;;
          --list|-l|--all|-a|--remotes|-r|--verbose|-v|-vv|--no-color|--merged|--no-merged|--contains|--no-contains|--sort*|--format*|--points-at*) ;;
          *) has_name=1 ;;
        esac
      done
      [ "$has_op" = 0 ] && [ "$has_name" = 0 ] && return 0
      return 1 ;;
    tag)
      for w in $rest; do
        case "$w" in
          -l|--list|--sort*|--format*|--column) has_list=1 ;;
          -a|-d|-f|-m|-s|-u|-e|--delete|--force|--annotate|--sign|--edit|--create-reflog|--points-at|--contains|--no-contains) has_op=1 ;;
          *) has_name=1 ;;
        esac
      done
      if [ "$has_op" = 0 ] && { [ "$has_name" = 0 ] || [ "$has_list" = 1 ]; }; then return 0; fi
      return 1 ;;
    config)
      for w in $rest; do
        case "$w" in
          --list|-l|--get|--get-all|--get-regexp|--get-color|--get-colorbool|--name-only|-z|--null) has_q=1 ;;
          --add|--unset|--unset-all|--remove-section|--rename-section|--replace-all|--replace-value|--global|--system|--edit|--file*) has_op=1 ;;
          --*) has_op=1 ;;
          *) npos=$((npos+1)) ;;
        esac
      done
      if [ "$has_op" = 0 ] && { [ "$has_q" = 1 ] || [ "$npos" -le 1 ]; }; then return 0; fi
      return 1 ;;
    remote)
      for w in $rest; do has_list=$w; break; done
      case "$has_list" in ""|-v|--verbose|show|get-url) return 0 ;; esac
      return 1 ;;
  esac
  return 1
}

git_readonly=0
case "$git_sub" in
  status|log|diff|show|rev-parse|ls-files|ls-tree|ls-remote|describe|name-rev|help|version) git_readonly=1 ;;
  branch|tag|config|remote)
    if readonly_git_query "$git_sub" "$git_rest"; then git_readonly=1; else git_readonly=0; fi ;;
  "") git_readonly=1 ;;             # bare `git` prints help -> read-only
  *) git_readonly=0 ;;              # everything else (add/commit/reset/push/...) is unsafe
esac

# jj subcommand + first argument, parsed AFTER skipping jj global options.
# jj accepts global options before the subcommand (e.g. `-R <path>`,
# `--repository <path>`, `--ignore-working-copy`, `--at-op <op>`); naively
# taking the token after `jj` would misread `jj -R path git push` as subcommand
# `-R` and let a `jj git push` slip through. Value-taking global options must
# consume their value (`-R`/`--repository <path>`, `--config <cfg>`,
# `--at-op <op>`, `--color <when>`, `--pager <when>`); otherwise the value
# would be misread as the subcommand and a later `git push` would be read as an
# argument (e.g. `jj --at-op abc git push` -> subcommand "abc" -> allowed).
# Skip option tokens (and the value consumed by a value-taking option), then
# the first non-option token is the real subcommand and the next is its first
# argument. The scan is anchored to the COMMAND-POSITION `jj` (the first segment
# whose leading verb is jj) so an argument-position `jj` token (argument
# smuggling, e.g. `echo jj log | jj op undo`) cannot masquerade as the
# invocation and misread a later `jj op undo` / `jj abandon @` / `jj file
# untrack` as a read-only `log`.
jj_sub=$(printf '%s' "$cmd" | awk '
  {
    n = split($0, seg, "|")
    for (s = 1; s <= n; s++) {
      m = split(seg[s], w, /[ \t]+/)
      li = 0
      for (i = 1; i <= m; i++) {
        if (w[i] == "") continue
        if (w[i] ~ /^[0-9]*>/) continue
        if (w[i] == "<") continue
        if (w[i] ~ /^>/) continue
        if (w[i] ~ /^[A-Za-z_][A-Za-z0-9_]*=$/) continue
        li = i; break
      }
      if (li && w[li] == "jj") {
        i = li + 1
        while (i <= m) {
          t = w[i]
          if (t ~ /^-/) {
            if (t == "-R" || t == "--repository" || t == "--at-op" ||
                t == "--config" || t == "--color" || t == "--pager") { i += 2; continue }
            if (t ~ /^--[A-Za-z0-9_.-]+=/) { i++; continue }
            i++; continue
          }
          print t; exit
        }
        exit
      }
    }
  }')
jj_arg2=$(printf '%s' "$cmd" | awk '
  {
    n = split($0, seg, "|")
    for (s = 1; s <= n; s++) {
      m = split(seg[s], w, /[ \t]+/)
      li = 0
      for (i = 1; i <= m; i++) {
        if (w[i] == "") continue
        if (w[i] ~ /^[0-9]*>/) continue
        if (w[i] == "<") continue
        if (w[i] ~ /^>/) continue
        if (w[i] ~ /^[A-Za-z_][A-Za-z0-9_]*=$/) continue
        li = i; break
      }
      if (li && w[li] == "jj") {
        i = li + 1
        subc=""
        while (i <= m) {
          t = w[i]
          if (t ~ /^-/) {
            if (t == "-R" || t == "--repository" || t == "--at-op" ||
                t == "--config" || t == "--color" || t == "--pager") { i += 2; continue }
            if (t ~ /^--[A-Za-z0-9_.-]+=/) { i++; continue }
            i++; continue
          }
          if (subc == "") { subc = t; i++; continue }
          print t; exit
        }
        exit
      }
    }
  }')
jj_mutating=0
# jj_banned / jj_banned_reason: subcommand families that are denied outright
# even in a clean, verifiable repo (they mutate or reach the git/remote layer).
jj_banned=0
jj_banned_reason=""
case "$jj_sub" in
  status|st|log|diff|show|obslog|root|rev) ;;
  op)
    case "$jj_arg2" in
      log|show|walk|"") ;;        # op undo/restore/abandon/... mutate the op log
      *) jj_banned=1; jj_banned_reason="$R_GIT_MUTATE" ;;
    esac ;;
  file)
    case "$jj_arg2" in
      show|list|annotate|"") ;;   # file untrack/track/chmod/expand/... mutate
      *) jj_banned=1; jj_banned_reason="$R_GIT_MUTATE" ;;
    esac ;;
  util|debug) jj_banned=1; jj_banned_reason="$R_GIT_MUTATE" ;;  # conservative deny
  config)
    case "$jj_arg2" in set) jj_mutating=1 ;; *) ;; esac ;;
  bookmark|branch)
    case "$jj_arg2" in list|get|"") ;; *) jj_mutating=1 ;; esac ;;
  git)
    # All jj git remote/clone/init and every jj git push force/ambiguous-target
    # form, plus other git-reaching mutations, are denied outright.
    case "$jj_arg2" in
      "") ;;                       # bare `jj git` prints help -> read-only
      *) jj_banned=1; jj_banned_reason="$R_GIT_MUTATE" ;;
    esac ;;
  edit|describe|untrack|chmod|new|squash|unsquash|absorb|amend|touch|set|split|duplicate|abandon|rebase|diffedit|restore|move|update|resolve|prev|next) jj_mutating=1 ;;
  "") ;;
  *) jj_mutating=1 ;;   # unknown jj subcommand -> conservative
esac

# ---- Belt-and-braces: stray `git` after a `jj` token ----
# Even with correct value consumption above, an unmodeled value-taking jj
# global option could still shift a later `git` word into a fake "subcommand"
# slot (e.g. `jj --unknown-opt tmp git push` would otherwise read subcommand
# "tmp" and allow). If a standalone `git` word appears positionally AFTER a
# `jj` word but is NOT the recognized jj git subcommand, a git mutating/staging
# operation has been smuggled inside a jj invocation -> deny. The legitimate
# `jj git ...` case is exactly ONE jj invocation (its `git` is the subcommand,
# already classified above), so it is exempt from this guard.
if [ "$has_jj" = 1 ]; then
  stray_git=$(printf '%s' "$cmd" | awk '
    {
      jpos = 0; gpos = 0
      for (i = 1; i <= NF; i++) {
        if ($i == "jj"  && jpos == 0) jpos = i
        if ($i == "git" && gpos == 0) gpos = i
      }
      if (jpos > 0 && gpos > jpos) print 1; else print 0
    }')
  if [ "$stray_git" = "1" ] && [ "$jj_sub" != "git" ]; then deny "$R_GIT_MUTATE"; fi
fi

# ---- 7. Repository discovery from the authoritative payload cwd ----
workdir=$cwd
[ -d "$workdir" ] || deny "$R_NON_REPO"

root=""
d=$workdir
while [ -n "$d" ] && [ "$d" != "/" ]; do
  if [ -e "$d/.jj" ] || [ -e "$d/.git" ]; then
    root=$d
    break
  fi
  d=$(dirname "$d")
done
[ "$root" != "/" ] || root=""

if [ -z "$root" ]; then
  # No repository: git/jj targets have nothing to operate on -> deny.
  [ "$has_git" = 1 ] || [ "$has_jj" = 1 ] && deny "$R_NON_REPO"
  allow
fi

# Normalize the discovered root to its physical (symlink-free) absolute path.
# `jj root` and `git rev-parse --show-toplevel` return canonical paths, so
# comparing them against a root that still contains symlink components (e.g.
# when the payload `cwd` arrives through a symlink) would spuriously mismatch
# and fail-safe on read-only queries. Canonicalizing here keeps those checks
# deterministic and correct.
root=$(cd "$root" 2>/dev/null && pwd -P 2>/dev/null) || deny "$R_NON_REPO"

jj_present=0
[ -e "$root/.jj" ] && jj_present=1
# Resolve the real git dir: `.git` may be a directory or a gitdir pointer file
# (worktrees / submodules store `gitdir: <path>`).
gitdir_path="$root/.git"
if [ -f "$root/.git" ]; then
  gd=$(sed -n 's/^gitdir:[[:space:]]*//p' "$root/.git" 2>/dev/null | head -n 1)
  if [ -n "$gd" ]; then
    case "$gd" in
      /*) gitdir_path="$gd" ;;
      *)  gitdir_path="$root/$gd" ;;
    esac
  fi
fi
colocated=0
[ -d "$gitdir_path" ] && colocated=1

cd "$root" || deny "$R_NON_REPO"

# ---- 8. Repository state checks ----
has_jj_bin=0
command -v jj >/dev/null 2>&1 && has_jj_bin=1
jj_meta_ok=0
gitop=0
conflicts=0
detached=0
git_ok=0
git_mismatch=0
jj_in_index=0
jj_not_ignored=0

# 8a. jj metadata: `jj root` must agree with the discovered root. A failing or
# mismatched root makes the state unverifiable (fail-safe: mutations denied).
# A failing conflict/bookmark query defaults to "no conflict"/"not detached"
# (a resolved/empty result) rather than tripping the metadata path.
if [ "$jj_present" = 1 ] && [ "$has_jj_bin" = 1 ]; then
  if jjroot=$(jj root --ignore-working-copy 2>/dev/null) && [ "$jjroot" = "$root" ]; then
    jj_meta_ok=1
    # 8b. conflict check via a valid real-jj read-only query. `-T description`
    # (a real template keyword — `-T x` is not): ANY output with a real jj means
    # at least one conflicted revision is present — including a bare newline,
    # which is what a conflicted revision with an EMPTY description produces.
    # We count bytes instead of testing `[ -n "$out" ]` because command
    # substitution strips a trailing newline: an empty-description conflicted
    # rev prints `\n` which `$(...)` collapses to "" and would otherwise be
    # misread as "no conflict". This block only runs when jj is present.
    conflict_bytes=$(jj --ignore-working-copy log -r 'conflicts()' --no-graph -T 'description' 2>/dev/null | wc -c)
    [ "$conflict_bytes" -gt 0 ] && conflicts=1
    # 8c. detached working-copy commit (no bookmark on @).
    out=$(jj --ignore-working-copy bookmark list -r '@' 2>/dev/null) || :
    [ -z "$out" ] && detached=1
  fi
fi

# 8e. git operation in progress (only when a git store is present).
if [ "$colocated" = 1 ]; then
  for m in MERGE_HEAD REBASE_HEAD CHERRY_PICK_HEAD BISECT_LOG sequencer rebase-merge rebase-apply index.lock; do
    if [ -e "$gitdir_path/$m" ]; then gitop=1; break; fi
  done
fi

# 8f. Git context check: confirm a real git repo whose toplevel is the root.
if command -v git >/dev/null 2>&1; then
  top=$(cd "$root" && git rev-parse --show-toplevel 2>/dev/null) || top=""
  if [ -n "$top" ]; then
    if [ "$top" = "$root" ]; then
      git_ok=1
    else
      git_mismatch=1
    fi
  fi
fi

# 8g. Read-only git index inspection for tracked/staged `.jj` descendants.
if [ "$git_ok" = 1 ]; then
  if [ -n "$(cd "$root" && git ls-files -- .jj 2>/dev/null | head -n 1)" ]; then
    jj_in_index=1
  fi
  if ! (cd "$root" && git check-ignore -q .jj 2>/dev/null); then
    jj_not_ignored=1
  fi
fi

# ---- 9. Deterministic decision ----
if [ "$has_git" = 1 ]; then
  # A git operation is in flight: deny all git commands until it clears.
  if [ "$gitop" = 1 ]; then deny "$R_GIT_OP"; fi
  # Git toplevel does not match the jj root: cannot verify context.
  if [ "$git_mismatch" = 1 ]; then deny "$R_METADATA"; fi
  # A detached working-copy commit takes precedence over a reported conflict
  # (its unambiguous, non-conflicting cause is the safer reading of the state),
  # and only blocks non-read-only git ops.
  if [ "$detached" = 1 ] && [ "$jj_present" = 1 ] && [ "$git_readonly" = 0 ]; then deny "$R_DETACHED"; fi
  # Conflicts in a jj repo: deny git access until resolved.
  if [ "$conflicts" = 1 ] && [ "$jj_present" = 1 ]; then deny "$R_CONFLICT"; fi
  # `.jj` internals tracked/staged in the git index: deny mutating/staging.
  if [ "$jj_in_index" = 1 ] && [ "$git_readonly" = 0 ]; then deny "$R_JJ_TRACKED"; fi
  # Broad git add with `.jj` not git-ignored risks staging jj internals.
  if [ "$git_broad_add" = 1 ] && [ "$jj_not_ignored" = 1 ]; then deny "$R_JJ_TRACKED"; fi
  # Read-only git subcommands are allowed when the state is clean.
  if [ "$git_readonly" = 1 ]; then
    if [ "$jj_present" = 1 ] && [ "$jj_meta_ok" = 0 ]; then deny "$R_METADATA"; fi
    allow
  fi
  if [ "$jj_present" = 1 ] && [ "$jj_meta_ok" = 0 ]; then deny "$R_METADATA"; fi
  deny "$R_GIT_MUTATE"
fi

# jj (or mixed) command path. A banned jj family counts as a write for the
# purposes of the state guards, but the guards take precedence so a banned op
# during an unresolved conflict / git-op reports the state reason first.
jj_write=0
[ "$jj_mutating" = 1 ] && jj_write=1
[ "$jj_banned" = 1 ] && jj_write=1
if [ "$jj_present" = 1 ] && [ "$jj_meta_ok" = 0 ] && [ "$has_jj_bin" = 1 ]; then
  # Cannot verify jj state; allow read-only, deny write/banned forms.
  if [ "$jj_write" = 1 ]; then deny "$R_METADATA"; fi
  allow
fi
if [ "$gitop" = 1 ] && [ "$jj_write" = 1 ]; then deny "$R_GIT_OP"; fi
if [ "$conflicts" = 1 ] && [ "$jj_present" = 1 ] && [ "$jj_write" = 1 ]; then deny "$R_CONFLICT"; fi
if [ "$detached" = 1 ] && [ "$jj_present" = 1 ] && [ "$jj_write" = 1 ]; then deny "$R_DETACHED"; fi
if [ "$jj_in_index" = 1 ] && [ "$jj_write" = 1 ]; then deny "$R_JJ_TRACKED"; fi

# Explicitly-banned jj families (op/file/util/debug misuse, jj git
# remote/clone/init, every jj git push force/ambiguous-target form) are denied
# even in a clean, verifiable repo.
if [ "$jj_banned" = 1 ]; then deny "$jj_banned_reason"; fi

allow
