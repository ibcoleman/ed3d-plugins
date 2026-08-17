#!/usr/bin/env python3
"""Standalone zero-dependency tests for check-review-loop.py."""
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
FORBIDDEN = ("set round", "set review.active", "verdict=SHIP", "consecutive_blocks=0", "review.active=false")


def check(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print("  PASS " + name)
    else:
        FAIL += 1
        FAILURES.append(name)
        print("  FAIL %s  %s" % (name, detail))


def make_tmp(state):
    root = tempfile.mkdtemp(prefix="ed3d-orchestrate-test-")
    os.makedirs(os.path.join(root, ".ed3d"))
    path = os.path.join(root, ".ed3d", "orchestrate-state.json")
    if state is not None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state, f)
    return root, path


def active(verdict="PENDING", round_=1, max_rounds=3, consecutive=None, nonce=None):
    review = {"active": True, "round": round_, "max_rounds": max_rounds, "verdict": verdict, "open_critical_high": []}
    if consecutive is not None:
        review["consecutive_blocks"] = consecutive
    if nonce is not None:
        review["nonce"] = nonce
    return {"task": "test", "phase": "review", "review": review}


def run(state, transcript=None, event_extra=None):
    root, state_path = make_tmp(state)
    event = {"cwd": root, "stop_hook_active": False}
    if event_extra:
        event.update(event_extra)
    if transcript is not None:
        transcript_path = os.path.join(root, "transcript.jsonl")
        with open(transcript_path, "w", encoding="utf-8") as f:
            f.write(transcript)
        event["transcriptPath"] = transcript_path
    proc = subprocess.run([sys.executable, HOOK], input=json.dumps(event).encode(), capture_output=True, cwd=root, timeout=15)
    output = proc.stdout.decode()
    decision = json.loads(output) if output.strip() else None
    return root, state_path, proc.returncode, output, decision


def reason_ok(decision, expected, needle=None):
    return decision is not None and decision.get("decision") == expected and (needle is None or needle in decision.get("reason", ""))


def state_after(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main():
    print("fail-open and baseline cases")
    root, _, code, out, _ = run(None)
    check("missing state -> silent allow", code == 0 and out == "")
    shutil.rmtree(root, ignore_errors=True)
    root, path = make_tmp(active())
    with open(path, "w") as f:
        f.write("{bad")
    proc = subprocess.run([sys.executable, HOOK], input=json.dumps({"cwd": root}).encode(), capture_output=True, cwd=root)
    check("malformed state -> silent allow", proc.returncode == 0 and proc.stdout == b"")
    shutil.rmtree(root, ignore_errors=True)
    root, _, code, out, _ = run({"review": {"active": False}})
    check("inactive review -> silent allow", code == 0 and out == "")
    shutil.rmtree(root, ignore_errors=True)
    root, _, code, out, _ = run(active(round_="bad"))
    check("malformed round -> silent allow", code == 0 and out == "")
    shutil.rmtree(root, ignore_errors=True)

    print("ordinary loop and diagnostic policy")
    root, path, code, out, decision = run(active(verdict="FIX-FIRST", round_=1))
    check("active FIX-FIRST -> block", reason_ok(decision, "block", "round 1 of 3"), out)
    check("ordinary block increments counter", state_after(path)["review"].get("consecutive_blocks") == 1)
    check("ordinary block has never-forward clause", "never forward" in decision["reason"].lower())
    check("ordinary reason has no forbidden imperative", not any(x in decision["reason"] for x in FORBIDDEN))
    shutil.rmtree(root, ignore_errors=True)
    root, _, _, _, decision = run(active(verdict="FIX-FIRST"), event_extra={"stop_hook_active": True})
    check("stop_hook_active -> block", reason_ok(decision, "block", "prior block"))
    check("stop_hook_active note delegates circuit break", "skill's circuit-break step" in decision["reason"] and not any(x in decision["reason"] for x in FORBIDDEN))
    shutil.rmtree(root, ignore_errors=True)
    root, _, _, _, decision = run(active(round_=4, max_rounds=3))
    check("round over cap -> allow", reason_ok(decision, "allow", "round 4 > max 3"))
    shutil.rmtree(root, ignore_errors=True)
    root, _, _, _, decision = run(active(consecutive=7))
    check("seven blocks -> allow", reason_ok(decision, "allow", "7 consecutive blocks"))
    shutil.rmtree(root, ignore_errors=True)

    print("terminal SHIP state enforcement")
    terminal_cases = [
        ("nonzero counter", {"active": False, "round": 1, "max_rounds": 3, "verdict": "SHIP", "consecutive_blocks": 1}),
        ("active true", {"active": True, "round": 1, "max_rounds": 3, "verdict": "SHIP", "consecutive_blocks": 0}),
        ("counter absent", {"active": False, "round": 1, "max_rounds": 3, "verdict": "SHIP"}),
    ]
    for label, review in terminal_cases:
        root, path, _, out, decision = run({"review": review})
        check("terminal SHIP %s -> repair block" % label, reason_ok(decision, "block", "fields are internally inconsistent"), out)
        check("terminal SHIP %s has never-forward clause" % label, "never forward" in decision["reason"].lower())
        check("terminal SHIP %s has no forbidden imperative" % label, not any(x in decision["reason"] for x in FORBIDDEN))
        shutil.rmtree(root, ignore_errors=True)
    root, _, _, _, decision = run({"review": {"active": False, "round": 1, "max_rounds": 3, "verdict": "SHIP", "consecutive_blocks": 0}})
    check("consistent terminal SHIP -> silent allow", decision is None)
    shutil.rmtree(root, ignore_errors=True)

    print("nonce verdict matrix")
    tagged = "adversary output\nVERDICT: SHIP [%s]\n"
    cases = [
        ("tagged active PENDING", active(verdict="PENDING", nonce="a1b2c3d4"), tagged % "a1b2c3d4", True),
        ("tagged without findings line", active(verdict="PENDING", nonce="a1b2c3d4"), tagged % "a1b2c3d4", True),
        ("untagged literal", active(verdict="PENDING", nonce="a1b2c3d4"), "VERDICT: SHIP\nhas_critical_or_high: false\n", False),
        ("no nonce skips scan", active(verdict="PENDING"), "VERDICT: SHIP [a1b2c3d4]\nhas_critical_or_high: false\n", False),
        ("wrong nonce skips scan", active(verdict="PENDING", nonce="a1b2c3d4"), tagged % "deadbeef", False),
        ("mixed case nonce normalizes", active(verdict="PENDING", nonce="A1B2C3D4"), tagged % "a1b2c3d4", True),
    ]
    for label, state, transcript, stale in cases:
        root, path, _, out, decision = run(state, transcript)
        expected = "stale" if stale else "ordinary"
        needle = "nonce-tagged SHIP verdict marker" if stale else "review loop active"
        check("%s -> %s block" % (label, expected), reason_ok(decision, "block", needle), out)
        check("%s no forbidden imperative" % label, not any(x in decision["reason"] for x in FORBIDDEN))
        if stale:
            check("%s has never-forward clause" % label, "never forward" in decision["reason"].lower())
        shutil.rmtree(root, ignore_errors=True)
    root, _, _, _, decision = run(active(verdict="PENDING", nonce="a1b2c3d4"), tagged % "a1b2c3d4" + "has_critical_or_high: false\n")
    check("tagged SHIP with findings line -> stale block", reason_ok(decision, "block", "nonce-tagged SHIP verdict marker"))
    shutil.rmtree(root, ignore_errors=True)
    root, _, _, _, decision = run(active(verdict="PENDING", nonce="a1b2c3d4"), tagged % "a1b2c3d4", {"stop_hook_active": True})
    check("stale path plus stop hook has no forbidden imperative", not any(x in decision["reason"] for x in FORBIDDEN))
    shutil.rmtree(root, ignore_errors=True)

    print("additional allow paths")
    root, _, _, _, decision = run(active(verdict="PENDING", round_=1, consecutive=7), tagged % "a1b2c3d4")
    check("nonce stale at cap -> allow", reason_ok(decision, "allow", "7 consecutive blocks"))
    shutil.rmtree(root, ignore_errors=True)
    root, _, _, _, decision = run(active(verdict="PENDING"), "VERDICT: SHIP\n", {"stop_hook_active": True})
    check("ordinary stop-hook path still delegates", "skill's circuit-break step" in decision["reason"])
    check("ordinary stop-hook path no forbidden imperative", not any(x in decision["reason"] for x in FORBIDDEN))
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
