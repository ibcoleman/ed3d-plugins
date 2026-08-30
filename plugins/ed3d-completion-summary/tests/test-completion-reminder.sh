#!/bin/sh
# test-completion-reminder.sh -- verifies the REAL Copilot CLI `sessionStart`
# command hook (plugins/ed3d-completion-summary/hooks/completion-reminder.sh):
# deterministic constant output regardless of stdin dialect/shape, exit 0,
# no side effects, no network, no repo access.
set -u

. "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)/lib/harness.sh"

t_plan 27

# stdin fixtures living in the sandbox
mksandbox
CAMEL="$SANDBOX/camel.json"
SNAKE="$SANDBOX/snake.json"
EMPTY="$SANDBOX/empty"
GARBAGE="$SANDBOX/garbage.bin"
printf '%s' '{"sessionId":"s1","timestamp":1234,"cwd":"/tmp/demo","source":"startup","initialPrompt":"hi"}' > "$CAMEL"
printf '%s' '{"hook_event_name":"SessionStart","session_id":"s2","cwd":"/tmp/demo","initial_prompt":"hi"}' > "$SNAKE"
: > "$EMPTY"
# binary garbage: guaranteed malformed, including NUL bytes
printf '\\x00\\x01\\x02\\xff\\xfe{"broken"' > "$GARBAGE"

# ---------------------------------------------------------------------------
# (a) valid camelCase stdin -> exit 0, byte-exact expected line
# ---------------------------------------------------------------------------
run_reminder "$CAMEL"
t_eq "$__rc" "0" "a: camelCase stdin -> exit 0"
t_eq "$__stderr" "" "a: no stderr emitted"
t_eq "$__stdout" "$EXPECTED_OUTPUT" "a: camelCase stdout exactly matches expected line"
# byte-exact comparison (pins single line + trailing newline policy)
printf '%s\n' "$EXPECTED_OUTPUT" > "$SANDBOX/expected"
t_ok_cmd "cmp -s '$SANDBOX/expected' '$__out'" "a: stdout is byte-exact (single line + trailing newline)"

# ---------------------------------------------------------------------------
# (b) VS Code snake_case stdin -> same output
# ---------------------------------------------------------------------------
run_reminder "$SNAKE"
t_eq "$__rc" "0" "b: snake_case stdin -> exit 0"
t_eq "$__stdout" "$EXPECTED_OUTPUT" "b: snake_case stdout exactly matches expected line"
t_ok_cmd "cmp -s '$SANDBOX/expected' '$__out'" "b: stdout byte-exact"

# ---------------------------------------------------------------------------
# (c) empty stdin -> same output, exit 0
# ---------------------------------------------------------------------------
run_reminder "$EMPTY"
t_eq "$__rc" "0" "c: empty stdin -> exit 0"
t_eq "$__stdout" "$EXPECTED_OUTPUT" "c: empty stdin stdout exactly matches expected line"
t_ok_cmd "cmp -s '$SANDBOX/expected' '$__out'" "c: stdout byte-exact"

# ---------------------------------------------------------------------------
# (d) malformed stdin (binary garbage) -> same output, exit 0
# ---------------------------------------------------------------------------
run_reminder "$GARBAGE"
t_eq "$__rc" "0" "d: malformed/binary stdin -> exit 0 (fail-open)"
t_eq "$__stdout" "$EXPECTED_OUTPUT" "d: malformed stdin stdout exactly matches expected line"
t_ok_cmd "cmp -s '$SANDBOX/expected' '$__out'" "d: stdout byte-exact"

# ---------------------------------------------------------------------------
# (e) determinism: identical output across runs
# ---------------------------------------------------------------------------
run_reminder "$CAMEL"; o1="$__stdout"; r1="$__rc"
run_reminder "$CAMEL"; o2="$__stdout"; r2="$__rc"
run_reminder "$CAMEL"; o3="$__stdout"; r3="$__rc"
t_eq "$r1" "0" "e: run1 exit 0"
t_eq "$o1" "$o2" "e: run1 == run2"
t_eq "$o2" "$o3" "e: run2 == run3"
t_eq "$o1" "$EXPECTED_OUTPUT" "e: every run equals the exact expected line"

# ---------------------------------------------------------------------------
# (f) scope: no side effects, no network, no repo paths
# ---------------------------------------------------------------------------
# 1. The hook performs no file writes: run it in a pristine temp cwd and assert
#    nothing new appears (besides our own redirected stdout/err files).
WRITEDIR="$SANDBOX/writedir"
mkdir -p "$WRITEDIR"
( cd "$WRITEDIR" && "$REAL_SH" "$HOOK" < "$EMPTY" >"$WRITEDIR/o" 2>"$WRITEDIR/e" )
f_rc=$?
t_eq "$f_rc" "0" "f: hook runs in pristine cwd, exit 0"
t_ok "[ -f '$WRITEDIR/o' ] && [ -f '$WRITEDIR/e' ] && [ \"\$(ls -A '$WRITEDIR' | wc -l)\" -eq 2 ]" \
    "f: no new files created in cwd (only our captured o/e)"
rm -rf "$WRITEDIR"

# 2. The hook uses no network commands and refers to no repo paths.
hook_src="$(cat "$HOOK")"
t_not_contains 'curl' "$hook_src" "f: no curl"
t_not_contains 'wget' "$hook_src" "f: no wget"
t_not_contains 'git ' "$hook_src" "f: no git invocation"
t_not_contains '.jj' "$hook_src" "f: no jj reference"
t_not_contains '.git' "$hook_src" "f: no .git reference"
t_not_contains 'python' "$hook_src" "f: no python (pure POSIX sh)"
t_not_contains 'jq' "$hook_src" "f: no jq dependency"

# 3. Hook is pure POSIX sh (dash-clean): shell syntax check under dash.
if command -v dash >/dev/null 2>&1; then
    t_ok_cmd "dash -n '$HOOK'" "f: hook parses under POSIX dash"
else
    t_ok_cmd "sh -n '$HOOK'" "f: hook parses under sh"
fi

cleanup_sandbox
t_done
