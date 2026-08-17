#!/usr/bin/env python3
"""preToolUse write-guard enforcing the adversary agent's no-writes rule.

Mechanical enforcement of a rule that prose alone could not hold. Blocks observed
write-class tools (edit, create, apply_patch) and tolerant legacy variants when
preToolUse toolCalls[] contains a write and sessionId identifies a subagent
context. The state-derived gate requires an active PENDING review. The verified
Copilot payload uses sessionId and toolCalls[].name; agentId/session_id and
legacy top-level toolName/tool_name are tolerated as fallbacks.

The orchestrator (UUID session id), inactive reviews, and the bug-fixer
(verdict FIX-FIRST) are never blocked. Fail-open everywhere: malformed input,
missing state file, or any internal error exits 0 with no output. Known gap:
bash redirection writes are not intercepted.
"""
import json
import os
import sys

STATE_RELPATH = os.path.join(".ed3d", "orchestrate-state.json")
WRITE_TOOLS = {"edit", "create", "apply_patch", "write", "Edit", "Write", "MultiEdit", "NotebookEdit"}


def emit_block(reason):
    print(json.dumps({"decision": "block", "reason": reason}))


def find_state_file(start_dir):
    directory = os.path.abspath(start_dir)
    while True:
        candidate = os.path.join(directory, STATE_RELPATH)
        if os.path.isfile(candidate):
            return candidate
        parent = os.path.dirname(directory)
        if parent == directory:
            return None
        directory = parent


def agent_context_id(event):
    for key in ("sessionId", "agentId", "session_id"):
        value = event.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def write_tool_names(event):
    tool_calls = event.get("toolCalls")
    if isinstance(tool_calls, list):
        return [
            call.get("name")
            for call in tool_calls
            if isinstance(call, dict) and isinstance(call.get("name"), str)
        ]
    fallback = event.get("toolName") or event.get("tool_name")
    return [fallback] if isinstance(fallback, str) else []


def main():
    raw = sys.stdin.read()
    try:
        event = json.loads(raw) if raw.strip() else {}
    except Exception:
        return
    if not isinstance(event, dict):
        return
    if not any(name in WRITE_TOOLS for name in write_tool_names(event)):
        return

    context_id = agent_context_id(event)
    if not context_id or not context_id.startswith("call_"):
        return

    cwd = event.get("cwd")
    if not isinstance(cwd, str) or not cwd:
        cwd = os.getcwd()
    state_path = find_state_file(cwd)
    if state_path is None:
        return
    try:
        with open(state_path, encoding="utf-8") as handle:
            state = json.load(handle)
    except Exception:
        return
    review = state.get("review")
    if not isinstance(review, dict):
        return
    if review.get("active") is not True or review.get("verdict") != "PENDING":
        return

    emit_block(
        "ed3d-orchestrate write-guard: the adversary never modifies the "
        "working tree - report findings in your response instead. Fixes are "
        "applied by the orchestrator's bug-fixer dispatch, never by the "
        "reviewer. State path: %s" % state_path
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
