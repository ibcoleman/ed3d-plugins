#!/usr/bin/env bash

cat <<EOF
{
  "hookSpecificOutput": {
    "hookEventName": "SessionStart",
    "additionalContext": "When instructed to use a 'general-purpose' agent, invoke the 'using-generic-agents' skill, which guides you on how to correctly use a generic agent."
  }
}
EOF

exit 0
