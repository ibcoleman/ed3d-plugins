#!/usr/bin/env bash

set -euo pipefail

# Determine plugin root directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
PLUGIN_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cat <<EOF
{
  "hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": "Before responding, check whether any available skills apply to this task. If a matching skill hasn't been activated in this session, use the Skill tool to activate it."
  }
}
EOF

exit 0
