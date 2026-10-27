#!/bin/sh
set -eu

script_dir=$(CDPATH= cd "$(dirname "$0")" && pwd -P)
repo_root=$(CDPATH= cd "$script_dir/../../.." && pwd -P)
checker=$script_dir/check-package.sh

fail() {
    printf 'FAIL: %s\n' "$*" >&2
    exit 1
}

[ -f "$checker" ] || fail "checker is missing: $checker"
command -v jq >/dev/null 2>&1 || fail "jq is required"

tmp_parent=$(CDPATH= cd "${TMPDIR:-/tmp}" && pwd -P)
fixture_root=$(mktemp -d "$tmp_parent/native-orchestration-check.XXXXXX")
fixture_root=$(CDPATH= cd "$fixture_root" && pwd -P)
case "$fixture_root" in
    "$tmp_parent"/native-orchestration-check.*) ;;
    *) fail "temporary fixture escaped its owned scope: $fixture_root" ;;
esac

cleanup() {
    case "$fixture_root" in
        "$tmp_parent"/native-orchestration-check.*) ;;
        *) printf 'Refusing cleanup outside fixture scope: %s\n' "$fixture_root" >&2; return ;;
    esac
    rm -f "$fixture_root/.claude-plugin/marketplace.json" "$fixture_root/manifest.tmp" \
        "$fixture_root/plugins/ed3d-native-orchestration/.claude-plugin/plugin.json" \
        "$fixture_root/plugins/ed3d-native-orchestration/skills/native-orchestration/SKILL.md" \
        "$fixture_root/plugins/ed3d-native-orchestration/README.md" \
        "$fixture_root/plugins/ed3d-native-orchestration/tests/acceptance.md" \
        "$fixture_root/CHANGELOG.md"
    rmdir "$fixture_root/plugins/ed3d-native-orchestration/skills/native-orchestration" \
        "$fixture_root/plugins/ed3d-native-orchestration/skills" \
        "$fixture_root/plugins/ed3d-native-orchestration/tests" \
        "$fixture_root/plugins/ed3d-native-orchestration/.claude-plugin" \
        "$fixture_root/plugins/ed3d-native-orchestration" \
        "$fixture_root/plugins" "$fixture_root/.claude-plugin" "$fixture_root"
}
trap cleanup 0

reset_fixture() {
    package=$fixture_root/plugins/ed3d-native-orchestration
    mkdir -p "$fixture_root/.claude-plugin" "$package/.claude-plugin" \
        "$package/skills/native-orchestration" "$package/tests"
    printf '%s\n' \
        '{' \
        '  "name": "ed3d-native-orchestration",' \
        '  "description": "Copilot-only advisory Agent Skill for direct work and parent-owned integration.",' \
        '  "version": "0.1.0",' \
        '  "author": {"name": "Ed", "email": "ed@example.test"},' \
        '  "license": "UNLICENSED",' \
        '  "keywords": ["skills", "workflow", "copilot-only"]' \
        '}' > "$package/.claude-plugin/plugin.json"
    printf '%s\n' \
        '{' \
        '  "name": "ed3d-plugins",' \
        '  "plugins": [' \
        '    {' \
        '      "name": "ed3d-native-orchestration",' \
        '      "source": "./plugins/ed3d-native-orchestration",' \
        '      "description": "Copilot-only advisory Agent Skill for direct work and parent-owned integration.",' \
        '      "version": "0.1.0",' \
        '      "author": {"name": "Ed", "email": "ed@example.test"},' \
        '      "license": "UNLICENSED",' \
        '      "keywords": ["skills", "workflow", "copilot-only"]' \
        '    }' \
        '  ]' \
        '}' > "$fixture_root/.claude-plugin/marketplace.json"
    printf '%s\n' \
        '---' \
        'name: native-orchestration' \
        'description: Guides direct work or native delegation through parent-owned integration.' \
        '---' \
        '# Native orchestration' > "$package/skills/native-orchestration/SKILL.md"
    printf '%s\n' '# Native orchestration' > "$package/README.md"
    printf '%s\n' '# Acceptance' > "$package/tests/acceptance.md"
    printf '%s\n' \
        '# Changelog' \
        '' \
        '## [ed3d-native-orchestration] [0.1.0]' \
        '' \
        'Initial candidate.' > "$fixture_root/CHANGELOG.md"
}

expect_pass() {
    if output=$(sh "$checker" "$fixture_root" 2>&1); then
        printf 'PASS: %s\n' "$1"
    else
        printf '%s\n' "$output" >&2
        fail "$1 should have passed"
    fi
}

expect_fail() {
    label=$1
    expected=$2
    if output=$(sh "$checker" "$fixture_root" 2>&1); then
        fail "$label unexpectedly passed"
    fi
    case "$output" in
        *"$expected"*) printf 'PASS: %s\n' "$label" ;;
        *) printf '%s\n' "$output" >&2; fail "$label did not report '$expected'" ;;
    esac
}

reset_fixture
expect_pass "complete synthetic package"

rm "$fixture_root/CHANGELOG.md"
expect_fail "missing root changelog" "missing required file"

reset_fixture
rm "$fixture_root/plugins/ed3d-native-orchestration/skills/native-orchestration/SKILL.md"
expect_fail "missing skill" "missing required file"

reset_fixture
jq '.version = "9.9.9"' "$fixture_root/plugins/ed3d-native-orchestration/.claude-plugin/plugin.json" > "$fixture_root/manifest.tmp"
mv "$fixture_root/manifest.tmp" "$fixture_root/plugins/ed3d-native-orchestration/.claude-plugin/plugin.json"
expect_fail "version mismatch" "manifest version must be 0.1.0"

reset_fixture
printf '%s\n' '{' > "$fixture_root/plugins/ed3d-native-orchestration/.claude-plugin/plugin.json"
expect_fail "malformed manifest JSON" "invalid JSON"

reset_fixture
printf '%s\n' \
    '---' \
    'name: native-orchestration' \
    'description: Guides direct work.' \
    'allowed-tools: [Bash]' \
    '---' \
    '# Native orchestration' > "$fixture_root/plugins/ed3d-native-orchestration/skills/native-orchestration/SKILL.md"
expect_fail "permission-expanding skill field" "permission-expanding field"

reset_fixture
jq '.hooks = {"PreToolUse": []}' "$fixture_root/plugins/ed3d-native-orchestration/.claude-plugin/plugin.json" > "$fixture_root/manifest.tmp"
mv "$fixture_root/manifest.tmp" "$fixture_root/plugins/ed3d-native-orchestration/.claude-plugin/plugin.json"
expect_fail "runtime registration" "runtime registration"

reset_fixture
jq '.plugins[0].version = "9.9.9"' "$fixture_root/.claude-plugin/marketplace.json" > "$fixture_root/manifest.tmp"
mv "$fixture_root/manifest.tmp" "$fixture_root/.claude-plugin/marketplace.json"
expect_fail "catalog version drift" "catalog field 'version' does not match"

reset_fixture
jq '.keywords = ["skills"]' "$package/.claude-plugin/plugin.json" > "$fixture_root/manifest.tmp"
mv "$fixture_root/manifest.tmp" "$package/.claude-plugin/plugin.json"
jq '.plugins[0].keywords = ["skills"]' "$fixture_root/.claude-plugin/marketplace.json" > "$fixture_root/manifest.tmp"
mv "$fixture_root/manifest.tmp" "$fixture_root/.claude-plugin/marketplace.json"
expect_fail "missing Copilot-only designation" "keywords must contain copilot-only"

reset_fixture
jq '.plugins[0].hooks = {}' "$fixture_root/.claude-plugin/marketplace.json" > "$fixture_root/manifest.tmp"
mv "$fixture_root/manifest.tmp" "$fixture_root/.claude-plugin/marketplace.json"
expect_fail "catalog runtime registration" "catalog contains a prohibited"

reset_fixture
printf '%s\n' '---' 'name: native-orchestration' 'description: Guides direct work.' \
    '"allowed-tools": [shell]' '---' > "$package/skills/native-orchestration/SKILL.md"
expect_fail "unsupported frontmatter syntax" "unsupported skill frontmatter field"

if output=$(sh "$checker" "$repo_root" 2>&1); then
    printf '%s\n' "$output"
    printf 'PASS: real repository package\n'
else
    printf '%s\n' "$output" >&2
    fail "real repository package"
fi
