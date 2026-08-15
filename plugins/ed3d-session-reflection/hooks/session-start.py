#!/usr/bin/env python3
"""
SessionStart hook for ed3d-session-reflection.

Reads session metadata from stdin and injects it as context so the harness
knows its own session ID and transcript path. Works with Claude Code's hook
protocol (transcript_path provided) and derives the transcript location for
GitHub Copilot CLI sessions (~/.copilot/session-state/<id>/events.jsonl).
"""

import json
import os
import sys


def _value_as_session_id(value):
    if isinstance(value, (str, int)):
        value = str(value)
        if value:
            return value
    return None


def main():
    try:
        input_data = json.load(sys.stdin)
        if not isinstance(input_data, dict):
            return

        data = input_data.get("data")
        candidates = [input_data.get("session_id"), input_data.get("sessionId")]
        if isinstance(data, dict):
            candidates.extend((data.get("session_id"), data.get("sessionId")))

        session_id = next(
            (value for candidate in candidates
             if (value := _value_as_session_id(candidate)) is not None),
            None,
        )
        if session_id is None:
            return

        transcript_path = None
        for key in ("transcript_path", "transcriptPath"):
            candidate = input_data.get(key)
            if isinstance(candidate, str) and candidate:
                transcript_path = candidate
                break

        copilot_transcript = False
        if transcript_path is None:
            candidate = os.path.expanduser(
                f"~/.copilot/session-state/{session_id}/events.jsonl"
            )
            if os.path.isfile(candidate):
                transcript_path = candidate
                copilot_transcript = True

        if transcript_path is None:
            return

        context = (
            f"<system-reminder>\n"
            f"Your session ID is {session_id} and your session transcript path "
            f"(JSONL) is {transcript_path}. "
        )
        if copilot_transcript:
            context += "This is a GitHub Copilot CLI events.jsonl transcript. "
        context += (
            "Do not reference the session ID or transcript path unless directed "
            "to do so by the operator.\n"
            "</system-reminder>"
        )

        output = {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": context,
            }
        }
        print(json.dumps(output))
    except Exception:
        return


if __name__ == "__main__":
    main()
