#!/bin/sh
# harness.sh -- shared POSIX-shell helpers for the jj-git-safety offline suite.
#
# This verifies the REAL Copilot CLI `preToolUse` command hook
# (plugins/ed3d-hook-jj-git-safety/hooks/jj-preflight.sh). Everything runs in temp
# sandboxes with a state-driven `jj` stub and the local, offline `jq` binary.
# No remote is ever contacted and nothing outside the sandbox is mutated.

set -u

# ---------------------------------------------------------------------------
# counters / TAP-ish reporting (pure POSIX)
# ---------------------------------------------------------------------------
__t_pass=0; __t_fail=0; __t_skip=0
t_plan() { echo "plan: $1"; }

t_ok() {
    if eval "$1" >/dev/null 2>&1; then
        __t_pass=$((__t_pass+1)); echo "ok    - ${2:-$1}"
    else
        __t_fail=$((__t_fail+1)); echo "not ok - ${2:-$1}"
    fi
}
t_eq() {
    if [ "$1" = "$2" ]; then __t_pass=$((__t_pass+1)); echo "ok    - ${3:-eq} (got '$1')"
    else __t_fail=$((__t_fail+1)); echo "not ok - ${3:-eq} (got '$1', want '$2')"; fi
}
t_ok_cmd() {
    # t_ok_cmd <shell-string> [label]  -- run as its own `sh -c` and pass iff exit 0
    if sh -c "$1" >/dev/null 2>&1; then
        __t_pass=$((__t_pass+1)); echo "ok    - ${2:-$1}"
    else
        __t_fail=$((__t_fail+1)); echo "not ok - ${2:-$1}"
    fi
}
t_ne() {
    if [ "$1" != "$2" ]; then __t_pass=$((__t_pass+1)); echo "ok    - ${3:-ne} (got '$1')"
    else __t_fail=$((__t_fail+1)); echo "not ok - ${3:-ne} (got '$1')"; fi
}
t_contains() {
    case "$2" in *"$1"*) __t_pass=$((__t_pass+1)); echo "ok    - ${3:-contains '$1'}" ;;
        *) __t_fail=$((__t_fail+1)); echo "not ok - ${3:-contains '$1'}";; esac
}
t_not_contains() {
    case "$2" in *"$1"*) __t_fail=$((__t_fail+1)); echo "not ok - ${3:-not-contains '$1'}" ;;
        *) __t_pass=$((__t_pass+1)); echo "ok    - ${3:-not-contains '$1'}";; esac
}
t_skip() { __t_skip=$((__t_skip+1)); echo "skip  - $1"; }
t_done() {
    echo "----------------------------------------------------------------"
    echo "# pass=$__t_pass fail=$__t_fail skip=$__t_skip"
    if [ "$__t_fail" -eq 0 ]; then echo "# RESULT: PASS"; return 0
    else echo "# RESULT: FAIL"; return 1; fi
}

# ---------------------------------------------------------------------------
# paths
# ---------------------------------------------------------------------------
TESTS_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
LIB_DIR="$TESTS_DIR/lib"
STUBBIN_DIR="$LIB_DIR/stubbin"
PKG_ROOT="$(CDPATH= cd -- "$TESTS_DIR/.." && pwd)"
REAL_JQ="$(command -v jq 2>/dev/null || true)"
REAL_SH="$(command -v sh 2>/dev/null || echo /bin/sh)"

# ---------------------------------------------------------------------------
# sandbox
# ---------------------------------------------------------------------------
SANDBOX=""
mksandbox() {
    [ -n "$SANDBOX" ] && return 0
    SANDBOX="$(mktemp -d "${TMPDIR:-/tmp}/jjgitsafety.XXXXXX")"
}
cleanup_sandbox() { [ -n "$SANDBOX" ] && rm -rf "$SANDBOX" && SANDBOX=""; }

# ---------------------------------------------------------------------------
# hook-under-test: always the real packaged hook (override with
# JJ_GIT_SAFETY_HOOK). Run via `$REAL_SH` so no exec bit is required.
# ---------------------------------------------------------------------------
HOOK="${JJ_GIT_SAFETY_HOOK:-$PKG_ROOT/hooks/jj-preflight.sh}"

# ---------------------------------------------------------------------------
# PATH builders. Coreutils plus the local jq are enough; we deliberately
# gate jq / jj per test to model "tool unavailable".
# ---------------------------------------------------------------------------
make_tools() {
    mksandbox
    tooldir="$SANDBOX/tools"
    [ -d "$tooldir" ] && { echo "$tooldir"; return; }
    mkdir -p "$tooldir"
    [ -n "$REAL_JQ" ] && [ ! -e "$tooldir/jq" ] && ln -s "$REAL_JQ" "$tooldir/jq" 2>/dev/null || true
    echo "$tooldir"
}
tools_path() { echo "$STUBBIN_DIR:$(make_tools):/usr/bin:/bin"; }

# ---------------------------------------------------------------------------
# HERMETIC PATH builders for "tool unavailable" tests.
#
# core_tools <dirname> <tool...>: create a dir holding symlinks to the resolved
# location of every core command the hook needs, OMITTING the named tool(s).
# This makes an unavailable tool genuinely absent regardless of the host's
# default PATH (a minimal, fully-controlled PATH — no /usr/bin:/bin fallback).
# ---------------------------------------------------------------------------
core_tools() {  # core_tools <dirname> <exclude-tool...>
    dir="$SANDBOX/$1"; shift; mkdir -p "$dir"
    for t in cat printf sed awk grep dirname jq jj; do
        skip=0
        for x in "$@"; do [ "$x" = "$t" ] && skip=1; done
        [ "$skip" = 1 ] && continue
        p=$(command -v "$t" 2>/dev/null || true)
        [ -n "$p" ] && [ ! -e "$dir/$t" ] && ln -s "$p" "$dir/$t" 2>/dev/null || true
    done
    echo "$dir"
}
# jq absent + jj stub present: minimal coreutils + stubbin (no jq anywhere).
minjq_path() { echo "$(core_tools nojq-tools jq):$STUBBIN_DIR"; }
# jj absent + jq present: minimal coreutils (incl. jq), no jj, no stubbin.
minjj_path() { echo "$(core_tools nojj-tools jj)"; }

# path_has <tool> <path>: exit 0 iff <tool> resolves on <path> (else 1).
path_has() {
    p="$1"; path="$2"
    _saved="$PATH"; PATH="$path"; export PATH
    if command -v "$p" >/dev/null 2>&1; then r=0; else r=1; fi
    PATH="$_saved"; export PATH
    return $r
}

# ---------------------------------------------------------------------------
# payload builders (use the real local jq to encode arbitrary command text)
# ---------------------------------------------------------------------------
mkpayload_obj() {  # <file> <cwd> <tool> <command...>
    file="$1"; cwd="$2"; tool="$3"; shift 3; cmd="$*"
    "$REAL_JQ" -n --arg c "$cwd" --arg t "$tool" --arg cmd "$cmd" \
        '{cwd:$c, toolName:$t, toolArgs:{command:$cmd}}' > "$file"
}
mkpayload_str() {  # <file> <cwd> <tool> <serialized-json-string e.g. '{"command":"git status"}'>
    file="$1"; cwd="$2"; tool="$3"; inner="$4"
    "$REAL_JQ" -n --arg c "$cwd" --arg t "$tool" --arg i "$inner" \
        '{cwd:$c, toolName:$t, toolArgs:$i}' > "$file"
}
mkpayload_arr() {  # <file> <cwd> <tool> <json-array-string e.g. '["git","status"]'>
    file="$1"; cwd="$2"; tool="$3"; arr="$4"
    "$REAL_JQ" -n --arg c "$cwd" --arg t "$tool" --argjson a "$arr" \
        '{cwd:$c, toolName:$t, toolArgs:$a}' > "$file"
}
# ---------------------------------------------------------------------------
# runner. run_hook <payload-file> <path-mode(tools|nojq|nojj|none)>
# sets __rc, __out(file), __err(file), __decision, __reason.
# ---------------------------------------------------------------------------
run_hook() {
    payload="$1"; mode="${2:-tools}"
    _saved_path="$PATH"
    case "$mode" in
        tools) PATH="$(tools_path)" ;;
        nojq)  PATH="$(minjq_path)" ;;
        nojj)  PATH="$(minjj_path)" ;;
        none)  PATH="/usr/bin:/bin" ;;
        *)     PATH="$(tools_path)" ;;
    esac
    export PATH
    __out="$SANDBOX/out"; __err="$SANDBOX/err"
    "$REAL_SH" "$HOOK" < "$payload" >"$__out" 2>"$__err"
    __rc=$?
    # restore PATH: hermetic modes must not leak into subsequent test steps
    PATH="$_saved_path"; export PATH
    __decision="$(cat "$__out" 2>/dev/null | "$REAL_JQ" -r '.permissionDecision // empty' 2>/dev/null || true)"
    __reason="$(  cat "$__out" 2>/dev/null | "$REAL_JQ" -r '.permissionDecisionReason // empty' 2>/dev/null || true)"
}

# decision/reason extractors for an already-written output file
decision() { cat "$1" | "$REAL_JQ" -r '.permissionDecision // empty' 2>/dev/null; }
reason()   { cat "$1" | "$REAL_JQ" -r '.permissionDecisionReason // empty' 2>/dev/null; }

# ---------------------------------------------------------------------------
# repo builders (filesystem structures the hook inspects)
# ---------------------------------------------------------------------------
newrepo() {  # newrepo <dir> <kind: jj|git|both|none>
    mkdir -p "$1"
    case "$2" in
        jj)   mkdir -p "$1/.jj" ;;
        git)  mkdir -p "$1/.git" ;;
        both) mkdir -p "$1/.jj" "$1/.git" ;;
        none) : ;;
    esac
}
gitop_mark() {  # gitop_mark <repo> <marker, e.g. MERGE_HEAD>
    mkdir -p "$1/.git"; : > "$1/.git/$2"
}
