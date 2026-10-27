#!/bin/sh
set -eu

fail() {
    printf 'error: %s\n' "$*" >&2
    exit 1
}

[ "$#" -eq 1 ] || fail "usage: check-package.sh REPOSITORY_ROOT"
command -v jq >/dev/null 2>&1 || fail "jq is required"
[ -d "$1" ] || fail "repository root is not a directory: $1"
root=$(CDPATH= cd "$1" && pwd -P) || fail "cannot resolve repository root: $1"
package=$root/plugins/ed3d-native-orchestration
manifest=$package/.claude-plugin/plugin.json
skill=$package/skills/native-orchestration/SKILL.md
catalog=$root/.claude-plugin/marketplace.json

for file in "$manifest" "$skill" "$package/README.md" "$package/tests/acceptance.md" \
    "$root/CHANGELOG.md" "$catalog"; do
    [ -f "$file" ] || fail "missing required file: $file"
done

jq -e . "$manifest" >/dev/null 2>&1 || fail "invalid JSON: $manifest"
jq -e . "$catalog" >/dev/null 2>&1 || fail "invalid JSON: $catalog"
jq -e 'type == "object"' "$manifest" >/dev/null 2>&1 ||
    fail "manifest must be a JSON object: $manifest"
jq -e 'type == "object" and (.plugins | type == "array")' "$catalog" >/dev/null 2>&1 ||
    fail "root catalog must contain a plugins array: $catalog"

require_string() {
    field=$1
    if ! jq -e --arg field "$field" 'has($field)' "$manifest" >/dev/null; then
        fail "manifest is missing required field '$field'"
    fi
    jq -e --arg field "$field" '.[$field] | type == "string" and length > 0' \
        "$manifest" >/dev/null 2>&1 ||
        fail "manifest field '$field' must be a nonempty string"
}

require_string name
require_string version
require_string description
require_string license
jq -e 'has("author")' "$manifest" >/dev/null ||
    fail "manifest is missing required field 'author'"
jq -e '.author | type == "object" and length > 0' "$manifest" >/dev/null 2>&1 ||
    fail "manifest field 'author' must be a nonempty object"
jq -e 'has("keywords")' "$manifest" >/dev/null ||
    fail "manifest is missing required field 'keywords'"
jq -e '.keywords | type == "array" and length > 0' "$manifest" >/dev/null 2>&1 ||
    fail "manifest field 'keywords' must be a nonempty array"
jq -e '.keywords | index("copilot-only") != null' "$manifest" >/dev/null 2>&1 ||
    fail "manifest keywords must contain copilot-only"

name=$(jq -r '.name' "$manifest")
version=$(jq -r '.version' "$manifest")
[ "$name" = "ed3d-native-orchestration" ] ||
    fail "manifest name mismatch: expected ed3d-native-orchestration, got $name"
[ "$version" = "0.1.0" ] ||
    fail "manifest version must be 0.1.0, got $version"

if jq -e 'has("hooks") or has("agents") or has("commands")' "$manifest" >/dev/null; then
    fail "manifest contains a prohibited hook, agent, or command runtime registration"
fi
for path in "$package/hooks" "$package/agents" "$package/commands" \
    "$package/.claude-plugin/hooks.json"; do
    if [ -f "$path" ] || [ -d "$path" ]; then
        fail "prohibited hook, agent, or command runtime registration: $path"
    fi
done

catalog_count=$(jq --arg name "$name" '[.plugins[] | select(.name == $name)] | length' "$catalog")
[ "$catalog_count" -eq 1 ] ||
    fail "root catalog must contain exactly one entry named '$name' (found $catalog_count)"
if jq -e --arg name "$name" '.plugins[] | select(.name == $name) |
    has("hooks") or has("agents") or has("commands")' "$catalog" >/dev/null; then
    fail "catalog contains a prohibited hook, agent, or command runtime registration"
fi

compare_catalog_field() {
    field=$1
    if ! jq -e --arg name "$name" --arg field "$field" \
        '.plugins[] | select(.name == $name) | has($field)' "$catalog" >/dev/null; then
        fail "catalog entry '$name' is missing required field '$field'"
    fi
    if ! jq -e --arg name "$name" --arg field "$field" --slurpfile manifest "$manifest" \
        '.plugins[] | select(.name == $name) | .[$field] == $manifest[0][$field]' \
        "$catalog" >/dev/null; then
        fail "catalog field '$field' does not match the manifest"
    fi
}

for field in name version description author license keywords; do
    compare_catalog_field "$field"
done
if ! jq -e --arg name "$name" \
    '.plugins[] | select(.name == $name) | has("source")' "$catalog" >/dev/null; then
    fail "catalog entry '$name' is missing required field 'source'"
fi
if ! jq -e --arg name "$name" \
    '.plugins[] | select(.name == $name) | .source == "./plugins/ed3d-native-orchestration"' \
    "$catalog" >/dev/null; then
    fail "catalog source for '$name' must be ./plugins/ed3d-native-orchestration"
fi

if frontmatter_error=$(awk '
function reject(message) {
    print "error: " message
    bad = 1
    exit 1
}
NR == 1 {
    if ($0 != "---") reject("skill frontmatter must start with ---")
    next
}
!closed && $0 == "---" {
    closed = 1
    next
}
!closed {
    key = $0
    sub(/^[[:space:]]+/, "", key)
    if (key ~ /^(allowed-tools|allowed_tools|permissions|tools|hooks|agents|commands|command)[[:space:]]*:/)
        reject("skill frontmatter contains a prohibited permission-expanding field or runtime registration")
    if ($0 !~ /^(name|description)[[:space:]]*:/)
        reject("unsupported skill frontmatter field; this package uses only plain name and description")
    if ($0 ~ /^name[[:space:]]*:/) {
        name_count++
        name_value = $0
        sub(/^name[[:space:]]*:[[:space:]]*/, "", name_value)
        sub(/[[:space:]]+$/, "", name_value)
    }
    if ($0 ~ /^description[[:space:]]*:/) {
        description_count++
        description_value = $0
        sub(/^description[[:space:]]*:[[:space:]]*/, "", description_value)
        sub(/[[:space:]]+$/, "", description_value)
    }
}
END {
    if (bad) exit 1
    if (!closed) { print "error: skill frontmatter is missing closing ---"; exit 1 }
    if (name_count != 1) { print "error: skill frontmatter must contain exactly one top-level name"; exit 1 }
    if (name_value != "native-orchestration") { print "error: skill frontmatter name must be native-orchestration"; exit 1 }
    if (description_count != 1 || description_value == "") { print "error: skill frontmatter needs one nonempty top-level description"; exit 1 }
}
' "$skill"); then
    :
else
    fail "$frontmatter_error"
fi

first_line=$(sed -n '1p' "$root/CHANGELOG.md")
[ "$first_line" = "# Changelog" ] ||
    fail "root changelog must start with '# Changelog'"
grep -Fqx '## [ed3d-native-orchestration] [0.1.0]' "$root/CHANGELOG.md" ||
    fail "root changelog is missing the 0.1.0 package header"

printf 'package check passed: %s %s\n' "$name" "$version"
