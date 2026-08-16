#!/usr/bin/env python3
"""Standalone tests for check-review-loop.py.

Run directly - no test framework required:

    python3 plugins/ed3d-orchestrate/hooks/test-check-review-loop.py

Zero external dependencies (json/os/shutil/subprocess/sys/tempfile only).
Exits nonzero if any case fails.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(HERE, "check-review-loop.py")

PASS = 0
FAIL = 0
FAILURES = []

CAMEL_EVENT = json.dumps(
    {
        "sessionId": "s-1",
        "timestamp": 1,
        "cwd": "__CWD__",
        "transcriptPath": "/dev/null",
        "stopReason": "end_turn",
        "stop_hook_active": False,
    }
)
PASCAL_EVENT = json.dumps(
    {
        "hook_event_name": "Stop",
        "session_id": "s-1",
        "timestamp": "2026-01-01T00:00:00Z",
        "cwd": "__CWD__",
        "transcript_path": "/dev/null",
        "stop_reason": "end_turn",
        "stop_hook_active": False,
    }
)


def run_hook(payload, cwd):
    proc = subprocess.run(
        [sys.executable, HOOK],
        input=payload.encode("utf-8"),
        capture_output=True,
        cwd=cwd,
        timeout=15,
    )
    return proc.returncode, proc.stdout.decode("utf-8")


def make_tmp(state=None, use_subdir=False):
    tmp = tempfile.mkdtemp(prefix="ed3d-orchestrate-test-")
    os.makedirs(os.path.join(tmp, ".ed3d"))
    state_path = os.path.join(tmp, ".ed3d", "orchestrate-state.json")
    if state is not None:
        with open(state_path, "w", encoding="utf-8") as handle:
            json.dump(state, handle)
    workdir = tmp
    if use_subdir:
        workdir = os.path.join(tmp, "packages", "app")
        os.makedirs(workdir)
    return tmp, state_path, workdir


def read_state(state_path):
    with open(state_path, encoding="utf-8") as handle:
        return json.load(handle)


def check(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print("  PASS %s" % name)
    else:
        FAIL += 1
        FAILURES.append(name)
        print("  FAIL %s  %s" % (name, detail))


def active_review(round_=1, max_rounds=3, verdict="FIX-FIRST", findings=None, consecutive=None):
    review = {
        "active": True,
        "round": round_,
        "max_rounds": max_rounds,
        "verdict": verdict,
        "open_critical_high": findings if findings is not None else [],
    }
    if consecutive is not None:
        review["consecutive_blocks"] = consecutive
    return {"task": "test task", "phase": "review", "review": review}


def parse_decision(stdout):
    return json.loads(stdout.strip())


def case(name, state, payload_template, use_subdir=False):
    """Shared runner: returns (tmp, state_path, exit, stdout, decision-or-None)."""
    tmp, state_path, workdir = make_tmp(state, use_subdir=use_subdir)
    payload = payload_template.replace("__CWD__", workdir)
    code, stdout = run_hook(payload, workdir)
    decision = None
    if stdout.strip():
        try:
            decision = parse_decision(stdout)
        except Exception:
            decision = None
    return tmp, state_path, code, stdout, decision


def cleanup(tmp):
    shutil.rmtree(tmp, ignore_errors=True)


def main():
    global PASS, FAIL

    print("fail-open cases")
    tmp, _, code, stdout, _ = case("no state file", None, CAMEL_EVENT)
    check("no state file -> silent allow", code == 0 and stdout == "", "code=%s stdout=%r" % (code, stdout))
    cleanup(tmp)

    tmp, state_path, workdir = make_tmp()
    with open(state_path, "w") as handle:
        handle.write("{not valid json")
    code, stdout = run_hook(CAMEL_EVENT.replace("__CWD__", workdir), workdir)
    check("malformed state JSON -> silent allow", code == 0 and stdout == "", "code=%s stdout=%r" % (code, stdout))
    cleanup(tmp)

    tmp, _, code, stdout, _ = case("no review key", {"task": "t", "phase": "review"}, CAMEL_EVENT)
    check("no review key -> silent allow", code == 0 and stdout == "")
    cleanup(tmp)

    tmp, _, code, stdout, _ = case(
        "review inactive",
        {"task": "t", "phase": "review", "review": {"active": False, "round": 2, "max_rounds": 3, "verdict": "FIX-FIRST"}},
        CAMEL_EVENT,
    )
    check("review.active false -> silent allow", code == 0 and stdout == "")
    cleanup(tmp)

    tmp, _, code, stdout, _ = case("verdict SHIP", active_review(round_=2, verdict="SHIP"), CAMEL_EVENT)
    check("verdict SHIP -> silent allow", code == 0 and stdout == "")
    cleanup(tmp)

    tmp, _, code, stdout, _ = case(
        "round not an int", active_review(round_="two"), CAMEL_EVENT
    )
    check("round malformed -> silent allow", code == 0 and stdout == "")
    cleanup(tmp)

    tmp, _, code, stdout, _ = case(
        "root not a dict", ["not", "a", "dict"], CAMEL_EVENT
    )
    check("state root not a dict -> silent allow", code == 0 and stdout == "")
    cleanup(tmp)

    code, stdout = run_hook("this is not json", os.getcwd())
    check("malformed stdin -> silent allow", code == 0 and stdout == "")

    print("block cases")
    tmp, state_path, code, stdout, decision = case(
        "block in budget",
        active_review(round_=1, max_rounds=3, verdict="FIX-FIRST", findings=["high: src/a.py:1 - breaks on empty input"]),
        CAMEL_EVENT,
    )
    ok = (
        code == 0
        and decision is not None
        and decision.get("decision") == "block"
        and "round 1 of 3" in decision.get("reason", "")
        and "FIX-FIRST" in decision.get("reason", "")
        and "src/a.py:1" in decision.get("reason", "")
    )
    check("active FIX-FIRST round 1/3 -> block", ok, "code=%s stdout=%r" % (code, stdout))
    after = read_state(state_path)
    check("block increments consecutive_blocks", after["review"].get("consecutive_blocks") == 1, "state=%r" % after)
    cleanup(tmp)

    tmp, _, code, stdout, decision = case(
        "block at boundary", active_review(round_=3, max_rounds=3, verdict="FIX-FIRST"), CAMEL_EVENT
    )
    ok = code == 0 and decision is not None and decision.get("decision") == "block" and "round 3 of 3" in decision.get("reason", "")
    check("round == max_rounds -> still block (in budget)", ok, "stdout=%r" % stdout)
    cleanup(tmp)

    tmp, _, code, stdout, decision = case(
        "no findings list", active_review(round_=1, verdict="PENDING", findings=None), CAMEL_EVENT
    )
    ok = code == 0 and decision is not None and decision.get("decision") == "block" and "Open findings:" not in decision.get("reason", "")
    check("PENDING verdict, no findings -> block without findings list", ok, "stdout=%r" % stdout)
    cleanup(tmp)

    tmp, _, code, stdout, decision = case(
        "pascal payload",
        active_review(round_=2, verdict="FIX-FIRST", findings=["critical: b.py:9 - SQL injection"]),
        PASCAL_EVENT,
        use_subdir=True,
    )
    ok = (
        code == 0
        and decision is not None
        and decision.get("decision") == "block"
        and "round 2 of 3" in decision.get("reason", "")
    )
    check("PascalCase Stop payload + subdir walk-up -> block", ok, "stdout=%r" % stdout)
    cleanup(tmp)

    tmp, state_path, workdir = make_tmp(active_review(round_=1, verdict="FIX-FIRST"))
    payload_json = json.loads(CAMEL_EVENT.replace("__CWD__", workdir))
    payload_json["stop_hook_active"] = True
    code, stdout = run_hook(json.dumps(payload_json), workdir)
    decision = parse_decision(stdout)
    check(
        "stop_hook_active -> block with prior-block note",
        decision.get("decision") == "block" and "prior block" in decision.get("reason", ""),
        "stdout=%r" % stdout,
    )
    cleanup(tmp)

    print("fallback cases")
    tmp, _, code, stdout, decision = case(
        "default max_rounds",
        {"task": "t", "phase": "review", "review": {"active": True, "round": 1, "verdict": "FIX-FIRST", "open_critical_high": []}},
        CAMEL_EVENT,
    )
    ok = code == 0 and decision is not None and decision.get("decision") == "block" and "round 1 of 3" in decision.get("reason", "")
    check("max_rounds absent -> default 3 applied", ok, "stdout=%r" % stdout)
    cleanup(tmp)

    tmp, _, workdir = make_tmp(active_review(round_=2, verdict="FIX-FIRST"))
    payload_json = json.loads(CAMEL_EVENT)
    del payload_json["cwd"]
    code, stdout = run_hook(json.dumps(payload_json), workdir)
    decision = parse_decision(stdout)
    check(
        "cwd absent -> process cwd fallback -> block",
        decision.get("decision") == "block" and "round 2 of 3" in decision.get("reason", ""),
        "stdout=%r" % stdout,
    )
    cleanup(tmp)

    print("allow cases")
    tmp, state_path, workdir = make_tmp(
        active_review(round_=4, max_rounds=3, verdict="FIX-FIRST", findings=["high: c.py:2 - x"])
    )
    before_bytes = open(state_path, "rb").read()
    code, stdout = run_hook(CAMEL_EVENT.replace("__CWD__", workdir), workdir)
    try:
        decision = parse_decision(stdout)
    except Exception:
        decision = None
    ok = (
        code == 0
        and decision is not None
        and decision.get("decision") == "allow"
        and "round 4 > max 3" in decision.get("reason", "")
        and "operator" in decision.get("reason", "")
    )
    check("round > max_rounds -> allow with operator prompt", ok, "stdout=%r" % stdout)
    check("allow leaves state file unchanged", open(state_path, "rb").read() == before_bytes)
    cleanup(tmp)

    tmp, _, code, stdout, decision = case(
        "consecutive cap", active_review(round_=1, verdict="FIX-FIRST", consecutive=7), CAMEL_EVENT
    )
    ok = (
        code == 0
        and decision is not None
        and decision.get("decision") == "allow"
        and "7 consecutive blocks" in decision.get("reason", "")
    )
    check("7 consecutive blocks -> allow with warning (never hard-lock)", ok, "stdout=%r" % stdout)
    cleanup(tmp)

    print("history-bearing state cases (review.history schema)")

    def hist():
        # fresh fixture per case, so one case can never mutate another's baseline
        return [
            {"round": 1, "verdict": "FIX-FIRST", "critical_high": 1, "advisory": 6},
            {"round": 2, "verdict": "PENDING", "critical_high": 0, "advisory": 0, "note": "adversary protocol failure"},
        ]

    state = active_review(round_=3, max_rounds=3, verdict="PENDING", findings=None)
    state["review"]["history"] = hist()
    tmp, state_path, code, stdout, decision = case("history + active PENDING", state, CAMEL_EVENT)
    ok = (
        code == 0
        and decision is not None
        and decision.get("decision") == "block"
        and "round 3 of 3" in decision.get("reason", "")
    )
    check("history present + PENDING in budget -> still blocks", ok, "stdout=%r" % stdout)
    after = read_state(state_path)
    check(
        "block rewrite preserves review.history (only consecutive_blocks mutates)",
        after["review"].get("history") == hist()
        and after["review"].get("consecutive_blocks") == 1,
        "state=%r" % after,
    )
    cleanup(tmp)

    state = active_review(round_=1, verdict="SHIP")
    state["review"]["history"] = hist()
    tmp, state_path, code, stdout, _ = case("history + SHIP", state, CAMEL_EVENT)
    check("history present + verdict SHIP -> silent allow", code == 0 and stdout == "", "code=%s stdout=%r" % (code, stdout))
    check("SHIP allow leaves history untouched", read_state(state_path)["review"].get("history") == hist())
    cleanup(tmp)

    state = active_review(round_=4, max_rounds=3, verdict="FIX-FIRST", findings=["high: c.py:2 - x"])
    state["review"]["history"] = hist()
    tmp, _, code, stdout, decision = case("history + over cap", state, CAMEL_EVENT)
    ok = (
        code == 0
        and decision is not None
        and decision.get("decision") == "allow"
        and "round 4 > max 3" in decision.get("reason", "")
        and "operator" in decision.get("reason", "")
    )
    check("history present + round > max_rounds -> allow with cap message", ok, "stdout=%r" % stdout)
    cleanup(tmp)

    print("idempotency")
    tmp, _, _, stdout1, _ = case("idempotent run 1", active_review(round_=2, verdict="FIX-FIRST"), CAMEL_EVENT)
    workdir = tmp
    payload = CAMEL_EVENT.replace("__CWD__", workdir)
    code2, stdout2 = run_hook(payload, workdir)
    check("same input -> same decision output", stdout1 == stdout2, "run1=%r run2=%r" % (stdout1, stdout2))
    cleanup(tmp)

    print("")
    print("results: %d passed, %d failed" % (PASS, FAIL))
    if FAILURES:
        print("failed cases:")
        for name in FAILURES:
            print("  - %s" % name)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
