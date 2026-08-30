#!/bin/sh
# test-package-layout.sh -- verifies the REAL jj-git-safety package layout and
# its install / uninstall / contract documentation are present and consistent.
#
# The package under test is plugins/ed3d-hook-jj-git-safety (PKG_ROOT). Fully offline;
# only inspects local files, never mutates, never contacts a remote.
set -u

. "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)/lib/harness.sh"

t_plan 56

PKG="$PKG_ROOT"
HOOKS="$PKG/hooks"
SKILL="$PKG/skills/jj-git-safety/SKILL.md"
HOOK_SCRIPT="$HOOKS/jj-preflight.sh"
HOOK_JSON="$HOOKS/jj-preflight.json"

# ---------------------------------------------------------------------------
# required files exist
# ---------------------------------------------------------------------------
test_required_files() {
    for f in "$PKG/README.md" "$HOOK_SCRIPT" "$HOOK_JSON" "$SKILL"; do
        t_ok "test -s '$f'" "layout: $(basename "$f") present and non-empty"
    done
    # Copilot-only package: no Claude Code plugin hook schema may ship, and the
    # native jj-preflight.json must be the ONLY runtime hook config in hooks/.
    t_ok "test ! -e '$HOOKS/hooks.json'" "layout: no hooks.json (Copilot-only, not Claude plugin)"
    t_eq "$(ls "$HOOKS" 2>/dev/null | grep -c '\.json$' || true)" "1" \
        "layout: jj-preflight.json is the only runtime hook config shipped"
}

# ---------------------------------------------------------------------------
# hook script: POSIX, executable, contract vocabulary, no bashisms
# ---------------------------------------------------------------------------
test_hook_script() {
    t_ok "grep -q '^#!.*sh' '$HOOK_SCRIPT'" "layout: hook is a shell script"
    t_ok "test -x '$HOOK_SCRIPT'" "layout: hook is executable"
    # POSIX syntax check (dash is the strictest common POSIX sh)
    if command -v dash >/dev/null 2>&1; then
        t_ok_cmd "dash -n '$HOOK_SCRIPT'" "layout: hook parses under POSIX dash"
    else
        t_ok_cmd "sh -n '$HOOK_SCRIPT'" "layout: hook parses under sh"
    fi
    # no bash-test constructs ([[ ... ]]) -- NB: POSIX [[:space:]] char classes
    # in sed/awk are legitimate, so only flag `[[`/`]]` followed by whitespace.
    t_ok_cmd "! grep -Eq '\[\[\s|\]\]\s|\]\]\$' '$HOOK_SCRIPT'" \
        "layout: no bash [[ test syntax (POSIX)"
    t_not_contains '=~' "$(cat "$HOOK_SCRIPT")" "layout: no bash =~ (POSIX)"
    t_not_contains 'local ' "$(cat "$HOOK_SCRIPT")" "layout: no 'local' (POSIX)"
    # fixed reason vocabulary present
    for reason in \
        "could not parse tool payload" \
        "no jj or git repository found for command target" \
        "git mutating/staging operation in a jj-managed repo" \
        "command is not a recognized read-only operation" \
        "compound or wrapped command with unsafe component" \
        "repository has unresolved conflicts" \
        "a git operation is in progress" \
        "working-copy commit is detached" \
        "could not verify jj metadata/repository state" \
        "jj internal state is tracked or stageable by git"; do
        t_contains "$reason" "$(cat "$HOOK_SCRIPT")" "layout: reason '$reason' in hook"
    done
    # fail-closed JSON emission paths exist
    t_contains 'permissionDecision' "$(cat "$HOOK_SCRIPT")" "layout: emits permissionDecision"
    t_contains '"deny"' "$(cat "$HOOK_SCRIPT")" "layout: emits deny"
    t_contains '"allow"' "$(cat "$HOOK_SCRIPT")" "layout: emits allow"
}

# ---------------------------------------------------------------------------
# hook config JSON: valid schema
# ---------------------------------------------------------------------------
test_hook_json() {
    t_ok_cmd "printf 'x' >/dev/null; \"$REAL_JQ\" -e . '$HOOK_JSON'" \
        "layout: jj-preflight.json is valid JSON"
    t_eq "$("$REAL_JQ" -r .version "$HOOK_JSON")" "1" "layout: version == 1"
    # preToolUse first entry
    t_eq "$("$REAL_JQ" -r '.hooks.preToolUse[0].type' "$HOOK_JSON")" "command" \
        "layout: hook type == command"
    t_eq "$("$REAL_JQ" -r '.hooks.preToolUse[0].matcher' "$HOOK_JSON")" "^bash$" \
        "layout: matcher anchored to bash"
    t_ok_cmd "[ -n \"\$(\"$REAL_JQ\" -r '.hooks.preToolUse[0].bash' '$HOOK_JSON')\" ]" \
        "layout: bash script path set"
    # timeoutSec must be set AND match the packaged value (5) — NOT the stale
    # documentation default; the test pins the actual shipped config.
    t_eq "$("$REAL_JQ" -r '.hooks.preToolUse[0].timeoutSec' "$HOOK_JSON")" "5" \
        "layout: timeoutSec == 5 (actual packaged value)"
    t_ok_cmd "\"$REAL_JQ\" -e '.hooks.preToolUse[0].timeoutSec == 5' '$HOOK_JSON'" \
        "layout: timeoutSec numeric 5 in config"
    # the referenced bash script exists
    ref="$(cd "$(dirname "$HOOK_JSON")" && "$REAL_JQ" -r '.hooks.preToolUse[0].bash' "$HOOK_JSON")"
    # relative to the hooks dir per the config's cwd
    base="$(dirname "$HOOK_JSON")"
    [ -f "$base/$ref" ] || [ -f "$ref" ]
    t_e=$?
    t_eq "$t_e" "0" "layout: config-referenced bash script resolves on disk"
}

# ---------------------------------------------------------------------------
# skill doc: frontmatter + required sections
# ---------------------------------------------------------------------------
test_skill_doc() {
    t_eq "$(sed -n 's/^name: *//p' "$SKILL" | head -1)" "jj-git-safety" \
        "skill: frontmatter name == jj-git-safety"
    s="$(cat "$SKILL")"
    t_contains 'user-invocable: false' "$s" "skill: user-invocable false"
    t_contains 'description:' "$s" "skill: has description"
    for sec in '## Scope' '## Safety Policy' '## Pre-Mutation Checklist' \
               '## Remediation' '## Limits' '# jj-git-safety'; do
        t_contains "$sec" "$s" "skill: section '$sec' present"
    done
}

# ---------------------------------------------------------------------------
# README: status, install / uninstall / layout docs
# ---------------------------------------------------------------------------
test_readme() {
    r="$(cat "$PKG/README.md")"
    t_contains 'INACTIVE' "$r" "readme: documents inactive status"
    t_contains 'not deployed' "$r" "readme: documents Copilot artifacts are not deployed"
    t_contains '## Install / Copy Paths' "$r" "readme: install/copy section present"
    t_contains '## Uninstall' "$r" "readme: uninstall section present"
    t_contains '~/.copilot/hooks' "$r" "readme: user-level hook path documented"
    t_contains '~/.copilot/skills/jj-git-safety' "$r" "readme: skill copy path documented"
    t_contains '.github/hooks' "$r" "readme: repo-level hook path documented"
    t_contains 'timeoutSec' "$r" "readme: documents timeout (fail-open) semantics"
    t_contains 'not a Claude Code plugin' "$r" "readme: explicitly documents Copilot-only scope"
}

# ---------------------------------------------------------------------------
# cross-file consistency: same policy vocabulary between README/skill/hook
# ---------------------------------------------------------------------------
test_cross_consistency() {
    # the skill and the hook must both say "prefer jj / deny git mutation"
    t_contains 'git reset --hard' "$(cat "$SKILL")" "consist: skill bans git reset --hard"
    t_contains 'force' "$(cat "$SKILL")" "consist: skill addresses force pushes"
    t_contains 'preToolUse' "$(cat "$PKG/README.md")" "consist: readme explains preToolUse"
    t_contains 'bash' "$(cat "$PKG/README.md")" "consist: readme covers bash-only scope"
}

# ---------------------------------------------------------------------------
# no symlink escapes the package root
# ---------------------------------------------------------------------------
test_no_symlink_escape() {
    escapes=""
    while IFS= read -r l; do
        tgt="$(readlink "$PKG/$l" 2>/dev/null || true)"
        [ -n "$tgt" ] || continue
        case "$tgt" in
            /*) escapes="$escapes $l($tgt)" ;;
            ../*|*"/../"*) escapes="$escapes $l($tgt)" ;;
        esac
    done <<EOF
$(cd "$PKG" && find . -type l 2>/dev/null | sed 's#^\./##')
EOF
    t_eq "$escapes" "" "layout: no symlink escapes the package root"
}

# ---------------------------------------------------------------------------
test_required_files
test_hook_script
test_hook_json
test_skill_doc
test_readme
test_cross_consistency
test_no_symlink_escape

cleanup_sandbox
t_done
