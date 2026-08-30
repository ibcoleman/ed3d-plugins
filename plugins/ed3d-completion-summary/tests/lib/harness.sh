#!/bin/sh
# harness.sh -- shared POSIX-shell helpers for the ed3d-completion-summary
# offline suite.
#
# This verifies the REAL Copilot CLI `sessionStart` command hook
# (plugins/ed3d-completion-summary/hooks/completion-reminder.sh). Everything
# runs in temp sandboxes; no remote is ever contacted and nothing outside the
# sandbox is mutated.

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
PKG_ROOT="$(CDPATH= cd -- "$TESTS_DIR/.." && pwd)"
REAL_SH="$(command -v sh 2>/dev/null || echo /bin/sh)"
REAL_JQ="$(command -v jq 2>/dev/null || true)"

# ---------------------------------------------------------------------------
# sandbox
# ---------------------------------------------------------------------------
SANDBOX=""
mksandbox() {
    [ -n "$SANDBOX" ] && return 0
    SANDBOX="$(mktemp -d "${TMPDIR:-/tmp}/compsummary.XXXXXX")"
}
cleanup_sandbox() { [ -n "$SANDBOX" ] && rm -rf "$SANDBOX" && SANDBOX=""; }

# ---------------------------------------------------------------------------
# hook-under-test: always the real packaged hook (override with
# COMPLETION_REMINDER_HOOK). Run via `$REAL_SH` so no exec bit is required.
# ---------------------------------------------------------------------------
HOOK="${COMPLETION_REMINDER_HOOK:-$PKG_ROOT/hooks/completion-reminder.sh}"
# Make HOOK/REAL_SH absolute (against the package root) so the sandbox `cd`
# in run_reminder cannot break resolution of relative overrides.
case "$HOOK" in /*) ;; *) HOOK="$PKG_ROOT/$HOOK" ;; esac
case "$REAL_SH" in /*) ;; *) REAL_SH="$PKG_ROOT/$REAL_SH" ;; esac

# ---------------------------------------------------------------------------
# The exact constant line the hook MUST emit (byte-exact, one line, trailing
# newline). The tests pin this string; change it only with the hook in lockstep.
# ---------------------------------------------------------------------------
EXPECTED_OUTPUT='{"additionalContext": "Session reminder: when a substantial work item completes in this session, prepare the work-completion-summary executive handoff (invoke the work-completion-summary skill) before stopping. Advisory only - never block on it."}'

# ---------------------------------------------------------------------------
# runner. run_reminder <stdin-file> [label]
# sets __rc, __out(file), __err(file), __stdout, __stderr.
# ---------------------------------------------------------------------------
run_reminder() {
    stdin="$1"
    mksandbox
    __out="$SANDBOX/out"; __err="$SANDBOX/err"
    ( cd "$SANDBOX" && "$REAL_SH" "$HOOK" < "$stdin" >"$__out" 2>"$__err" )
    __rc=$?
    __stdout="$(cat "$__out" 2>/dev/null || true)"
    __stderr="$(cat "$__err" 2>/dev/null || true)"
}
