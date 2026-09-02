#!/bin/sh
# test-package-layout.sh -- verifies the REAL ed3d-completion-summary package
# layout and that its install / contract documentation is present and
# consistent. Fully offline; only inspects local files, never mutates, never
# contacts a remote.
set -u

. "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)/lib/harness.sh"

t_plan 42

PKG="$PKG_ROOT"
HOOKS="$PKG/hooks"
SKILL="$PKG/skills/work-completion-summary/SKILL.md"
HOOK_SCRIPT="$HOOKS/completion-reminder.sh"
HOOK_JSON="$HOOKS/completion-reminder.json"

# ---------------------------------------------------------------------------
# required files exist
# ---------------------------------------------------------------------------
for f in "$PKG/README.md" "$HOOK_SCRIPT" "$HOOK_JSON" "$SKILL" \
         "$PKG/.claude-plugin/plugin.json" \
         "$PKG/tests/run-all.sh" "$PKG/tests/README.md" \
         "$PKG/tests/lib/harness.sh" \
         "$PKG/tests/test-completion-reminder.sh" \
         "$PKG/tests/test-package-layout.sh"; do
    t_ok "test -s '$f'" "layout: $(basename "$f") present and non-empty"
done

# Copilot-only package: no Claude Code plugin hook schema may ship (no
# hooks.json anywhere in the package).
t_ok "[ -z \"\$(find \"\$PKG\" -name hooks.json -print -quit)\" ]" "layout: no hooks.json anywhere (Copilot-only, not Claude plugin)"

# ---------------------------------------------------------------------------
# SKILL.md frontmatter
# ---------------------------------------------------------------------------
skill_dir="$(basename "$PKG/skills/work-completion-summary")"
t_eq "$skill_dir" "work-completion-summary" "skill: dir name is work-completion-summary"
t_eq "$(sed -n 's/^name: *//p' "$SKILL" | head -1)" "work-completion-summary" \
    "skill: frontmatter name == directory name (work-completion-summary)"

desc_line="$(grep -E '^description:' "$SKILL" | head -1)"
t_ne "$desc_line" "" "skill: description key present"
desc_val_raw="$(printf '%s' "$desc_line" | sed 's/^description:[[:space:]]*//')"
case "$desc_val_raw" in
    '"'*) dq=1 ;; *) dq=0 ;;
esac
t_eq "$dq" "1" "skill: description is quoted"
# description value must be <= 1024 chars (hard cap; over-cap skills are dropped)
desc_val="$(printf '%s' "$desc_val_raw" | sed 's/^"//; s/"$//')"
n="${#desc_val}"
t_ok "[ '$n' -le 1024 ]" "skill: description length $n <= 1024"

# no user-invocable key (custom-agent field, NOT a skill field) — frontmatter
# key specifically (prose uses of "user-invocable" in the body are fine)
t_ok_cmd "! grep -qE '^user-invocable' '$SKILL'" "skill: no user-invocable frontmatter key"

# body covers invocation framing
s="$(cat "$SKILL")"
t_contains 'Ground truth first' "$s" "skill: documents ground-truth-first"
t_contains '## Status' "$s" "skill: documents Status section"
t_contains '## Verification' "$s" "skill: documents Verification section"
t_contains '/work-completion-summary' "$s" "skill: slash-invocable path documented"

# ---------------------------------------------------------------------------
# plugin.json manifest
# ---------------------------------------------------------------------------
PJ="$PKG/.claude-plugin/plugin.json"
t_ok_cmd "\"$REAL_JQ\" -e . '$PJ'" "manifest: plugin.json is valid JSON"
t_eq "$("$REAL_JQ" -r .name "$PJ")" "ed3d-completion-summary" "manifest: name == ed3d-completion-summary"
t_eq "$("$REAL_JQ" -r .version "$PJ")" "0.1.0" "manifest: version == 0.1.0"
t_ok_cmd "\"$REAL_JQ\" -e '.keywords | index(\"copilot-only\")' '$PJ'" \
    "manifest: has copilot-only keyword"
t_ok_cmd "\"$REAL_JQ\" -e '.keywords | index(\"skills\")' '$PJ'" "manifest: has skills keyword"
t_ok_cmd "\"$REAL_JQ\" -e '.keywords | index(\"hooks\")' '$PJ'" "manifest: has hooks keyword"

# ---------------------------------------------------------------------------
# hook config JSON: valid schema, version 1, no matcher, no powershell
# ---------------------------------------------------------------------------
t_ok_cmd "\"$REAL_JQ\" -e . '$HOOK_JSON'" "hook-json: completion-reminder.json is valid JSON"
t_eq "$("$REAL_JQ" -r .version "$HOOK_JSON")" "1" "hook-json: version == 1"
t_eq "$("$REAL_JQ" -r '.hooks.sessionStart[0].type' "$HOOK_JSON")" "command" \
    "hook-json: sessionStart type == command"
t_ok_cmd "\"$REAL_JQ\" -e '.hooks.sessionStart[0] | has(\"matcher\") | not' '$HOOK_JSON'" \
    "hook-json: no matcher key (sessionStart schema does not take matcher)"
t_ok_cmd "\"$REAL_JQ\" -e '.hooks.sessionStart[0] | has(\"powershell\") | not' '$HOOK_JSON'" \
    "hook-json: no powershell key (POSIX/WSL only)"
t_eq "$("$REAL_JQ" -r '.hooks.sessionStart[0].timeoutSec' "$HOOK_JSON")" "5" \
    "hook-json: timeoutSec == 5"
# the referenced bash script resolves relative to the config's cwd
ref="$(cd "$(dirname "$HOOK_JSON")" && "$REAL_JQ" -r '.hooks.sessionStart[0].bash' "$HOOK_JSON")"
[ -f "$HOOKS/$ref" ]
t_eq "$?" "0" "hook-json: config-referenced bash script resolves on disk"

# ---------------------------------------------------------------------------
# README: install paths for BOTH artifacts + contract documentation
# ---------------------------------------------------------------------------
r="$(cat "$PKG/README.md")"
t_contains 'INACTIVE' "$r" "readme: documents inactive status"
t_contains '## Install / Copy Paths' "$r" "readme: install/copy section present"
t_contains '.github/hooks' "$r" "readme: hook repo-local copy path documented"
t_contains '~/.copilot/skills/work-completion-summary' "$r" "readme: skill copy path documented"
t_contains '.github/skills/work-completion-summary' "$r" "readme: repo-local skill option documented"
t_contains '"additionalContext"' "$r" "readme: documents sessionStart output contract"
t_contains 'version-coupl' "$r" "readme: documents version-coupled sessionStart output-shape limitation"
t_contains 'pattern-documented' "$r" "readme: documents output shape is under-documented (pattern, not schema)"

cleanup_sandbox
t_done
