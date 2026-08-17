#!/usr/bin/env python3
"""Standalone zero-dependency tests for adversary-write-guard.py."""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(HERE, "adversary-write-guard.py")
PASS = 0
FAIL = 0
FAILURES = []


def check(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print("  PASS " + name)
    else:
        FAIL += 1
        FAILURES.append(name)
        print("  FAIL %s  %s" % (name, detail))


def state(active=True, verdict="PENDING", round_=1):
    return {"task": "test", "review": {"active": active, "verdict": verdict, "round": round_}}


def run(payload, state_data=None):
    root = tempfile.mkdtemp(prefix="ed3d-write-guard-test-")
    os.makedirs(os.path.join(root, ".ed3d"))
    state_path = os.path.join(root, ".ed3d", "orchestrate-state.json")
    if state_data is not None:
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(state_data, f)
    payload = dict(payload)
    payload.setdefault("cwd", root)
    proc = subprocess.run([sys.executable, HOOK], input=json.dumps(payload).encode(), capture_output=True, cwd=root, timeout=15)
    out = proc.stdout.decode()
    decision = json.loads(out) if out.strip() else None
    return root, state_path, proc.returncode, out, decision


def write_payload(name="edit", session="call_xxx"):
    return {"cwd": "__set__", "sessionId": session, "toolCalls": [{"id": "call_1", "name": name, "args": "..."}]}


def main():
    print("observed payload and write matrix")
    for label, payload, round_ in [
        ("edit round 1", write_payload(), 1),
        ("edit round 3", write_payload(), 3),
        ("apply_patch", write_payload("apply_patch"), 1),
        ("create", write_payload("create"), 1),
    ]:
        payload.pop("cwd")
        root, path, code, out, decision = run(payload, state(round_=round_))
        check(label + " -> block", code == 0 and decision and decision.get("decision") == "block", out)
        check(label + " reason names state path", path in decision.get("reason", ""))
        shutil.rmtree(root, ignore_errors=True)

    root, _, _, out, decision = run({"sessionId": "call_multi", "toolCalls": [{"id": "1", "name": "view", "args": ""}, {"id": "2", "name": "edit", "args": ""}]}, state())
    check("multi-call read plus write -> block", decision and decision.get("decision") == "block", out)
    shutil.rmtree(root, ignore_errors=True)

    print("allow matrix")
    for name in ("view", "bash", "glob"):
        root, _, _, out, decision = run({"sessionId": "call_read", "toolCalls": [{"id": "1", "name": name, "args": ""}]}, state())
        check(name + " under call session -> allow", out == "" and decision is None)
        shutil.rmtree(root, ignore_errors=True)
    root, _, _, out, decision = run(write_payload(), state(verdict="FIX-FIRST"))
    check("FIX-FIRST -> allow", out == "" and decision is None)
    shutil.rmtree(root, ignore_errors=True)
    root, _, _, out, decision = run(write_payload(), state(active=False))
    check("inactive -> allow", out == "" and decision is None)
    shutil.rmtree(root, ignore_errors=True)
    root, _, _, out, decision = run(write_payload(session="12345678-1234-1234-1234-123456789012"), state())
    check("parent UUID session -> allow", out == "" and decision is None)
    shutil.rmtree(root, ignore_errors=True)

    print("fallback and fail-open matrix")
    root, _, _, out, decision = run({"sessionId": "call_fallback", "toolName": "edit"}, state())
    check("top-level toolName fallback -> block", decision and decision.get("decision") == "block", out)
    shutil.rmtree(root, ignore_errors=True)
    root, _, _, out, decision = run({"sessionId": "call_fallback", "tool_name": "edit"}, state())
    check("top-level tool_name fallback -> block", decision and decision.get("decision") == "block", out)
    shutil.rmtree(root, ignore_errors=True)
    root, _, _, out, decision = run({"sessionId": "call_x", "toolCalls": [{"name": "edit"}]}, None)
    check("missing state -> allow", out == "" and decision is None)
    shutil.rmtree(root, ignore_errors=True)
    root = tempfile.mkdtemp(prefix="ed3d-write-guard-test-")
    proc = subprocess.run([sys.executable, HOOK], input=b"not json", capture_output=True, cwd=root)
    check("malformed stdin -> allow", proc.returncode == 0 and proc.stdout == b"")
    shutil.rmtree(root, ignore_errors=True)
    root, _, _, out, decision = run({"toolCalls": [{"name": "edit"}]}, state())
    check("missing sessionId -> allow", out == "" and decision is None)
    shutil.rmtree(root, ignore_errors=True)
    root, _, _, out, decision = run({"sessionId": "call_x", "toolCalls": [{"name": "edit"}], "agentName": "adversary"}, None)
    check("adversary agentName without state -> allow", out == "" and decision is None)
    shutil.rmtree(root, ignore_errors=True)

    print("\nresults: %d passed, %d failed" % (PASS, FAIL))
    if FAILURES:
        print("failed cases:")
        for failure in FAILURES:
            print("  - " + failure)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
