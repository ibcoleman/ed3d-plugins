#!/usr/bin/env python3
"""
SessionStart hook for ed3d-session-reflection.

Reads session metadata from stdin and injects it as context so Claude
knows its own session ID and transcript path.
"""

import json
import sys


def main():
    try:
        input_data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        sys.exit(0)

    session_id = input_data.get("session_id", "")
    transcript_path = input_data.get("transcript_path", "")
    source = input_data.get("source", "")

    if not session_id:
        sys.exit(0)

    output = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": (
                f"<system-reminder>\n"
                f"Your Claude Code session ID is {session_id} "
                f"and your current Claude Code transcript path (JSONL) is {transcript_path}. "
                f"Do not reference the session ID or transcript path unless directed to do so by the operator.\n"
                f"</system-reminder>"
            ),
        }
    }
    print(json.dumps(output))
    sys.exit(0)


if __name__ == "__main__":
    main()
