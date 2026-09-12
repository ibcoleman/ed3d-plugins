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
    return {
        "task": "test",
        "phase": "review",
        "ownership": {"status": "owned", "session_id": "owner-session", "transfer_from": None},
        "review": review,
    }


def run(state, transcript=None, event_extra=None):
    root, state_path = make_tmp(state)
    event = {"cwd": root, "stop_hook_active": False, "sessionId": "owner-session"}
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


def run_with_snapshot(state, event_extra=None):
    root, state_path = make_tmp(state)
    before = open(state_path, "rb").read()
    event = {"cwd": root, "stop_hook_active": False, "sessionId": "owner-session"}
    if event_extra:
        event.update(event_extra)
    proc = subprocess.run(
        [sys.executable, HOOK],
        input=json.dumps(event).encode(),
        capture_output=True,
        cwd=root,
        timeout=15,
    )
    output = proc.stdout.decode()
    decision = json.loads(output) if output.strip() else None
    after = open(state_path, "rb").read()
    return root, proc.returncode, output, decision, before, after


def lineage_state(verdict="PENDING", nonce="a1b2c3d4", provenance=None):
    state = active(verdict=verdict, nonce=nonce)
    state["review"]["provenance"] = provenance
    return state


def lineage_transcript(
    dispatch="call_dispatch",
    reviewer="agent-reviewer",
    nonce="a1b2c3d4",
    verdict="SHIP",
    critical_high="false",
    content_prefix="review complete",
    trailing="",
):
    return "\n".join(
        [
            json.dumps(
                {
                    "type": "assistant.message",
                    "data": {"toolRequests": [{"toolCallId": dispatch, "name": "Task"}]},
                }
            ),
            json.dumps(
                {
                    "type": "tool.execution_start",
                    "data": {"toolCallId": dispatch},
                }
            ),
            json.dumps(
                {
                    "type": "subagent.started",
                    "agentId": reviewer,
                    "data": {
                        "toolCallId": dispatch,
                        "agentName": "adversary",
                    },
                }
            ),
            json.dumps(
                {
                    "type": "assistant.message",
                    "agentId": reviewer,
                    "data": {
                        "content": (
                            content_prefix
                            + "\nVERDICT: %s [%s]\n"
                            % (verdict, nonce)
                            + "has_critical_or_high: %s" % critical_high
                            + trailing
                        )
                    },
                }
            ),
            json.dumps(
                {
                    "type": "subagent.completed",
                    "agentId": reviewer,
                    "data": {"toolCallId": dispatch},
                }
            ),
        ]
    ) + "\n"


def lineage_without_dispatch_observation(transcript, event_type):
    lines = []
    for line in transcript.splitlines():
        event = json.loads(line)
        if event.get("type") == event_type and "agentId" not in event:
            continue
        lines.append(line)
    return "\n".join(lines) + "\n"


def duplicate_dispatch_observation(transcript, event_type):
    lines = transcript.splitlines()
    for index, line in enumerate(lines):
        event = json.loads(line)
        if event.get("type") == event_type and "agentId" not in event:
            lines.insert(index + 1, line)
            break
    return "\n".join(lines) + "\n"


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
    root, _, code, out, decision = run({"review": {"active": False}})
    check("inactive legacy review -> recovery allow", code == 0 and reason_ok(decision, "allow", "ownership-recovery-required"))
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
        root, path, _, out, decision = run(
            {"ownership": {"status": "owned", "session_id": "owner-session", "transfer_from": None}, "review": review}
        )
        check("terminal SHIP %s -> repair block" % label, reason_ok(decision, "block", "fields are internally inconsistent"), out)
        check("terminal SHIP %s has never-forward clause" % label, "never forward" in decision["reason"].lower())
        check("terminal SHIP %s has no forbidden imperative" % label, not any(x in decision["reason"] for x in FORBIDDEN))
        shutil.rmtree(root, ignore_errors=True)
    root, _, _, _, decision = run(
        {
            "ownership": {"status": "owned", "session_id": "owner-session", "transfer_from": None},
            "review": {"active": False, "round": 1, "max_rounds": 3, "verdict": "SHIP", "consecutive_blocks": 0},
        }
    )
    check("consistent terminal SHIP -> silent allow", decision is None)
    shutil.rmtree(root, ignore_errors=True)

    print("owner isolation and lineage reconciliation")
    owner_state = active(verdict="PENDING", nonce="a1b2c3d4")
    root, _, out, decision, before, after = run_with_snapshot(
        owner_state, event_extra={"sessionId": "other-session"}
    )
    check("non-owner stop -> silent allow", out == "" and decision is None)
    check("non-owner stop leaves state bytes unchanged", after == before)
    shutil.rmtree(root, ignore_errors=True)
    root, _, _, out, decision = run(owner_state, event_extra={"sessionId": None, "session_id": "other-session"})
    check("session_id non-owner stop -> silent allow", out == "" and decision is None)
    shutil.rmtree(root, ignore_errors=True)
    root, path, _, out, decision = run(owner_state)
    check("owner pending review -> block", reason_ok(decision, "block", "review loop active"), out)
    check("owner pending review increments counter", state_after(path)["review"]["consecutive_blocks"] == 1)
    shutil.rmtree(root, ignore_errors=True)

    transfer_state = active()
    transfer_state["ownership"] = {
        "status": "transfer_pending",
        "session_id": "old-owner",
        "transfer_from": "old-owner",
    }
    root, path, _, out, decision = run(transfer_state, event_extra={"sessionId": "old-owner"})
    check("transfer old owner -> allow unchanged", reason_ok(decision, "allow") and "recovery" not in decision["reason"], out)
    check("transfer old owner leaves state unchanged", state_after(path) == transfer_state)
    shutil.rmtree(root, ignore_errors=True)
    root, path, _, out, decision = run(transfer_state, event_extra={"session_id": "new-owner"})
    check("transfer pre-claim new owner -> silent allow", out == "" and decision is None)
    check("transfer pre-claim leaves state unchanged", state_after(path) == transfer_state)
    shutil.rmtree(root, ignore_errors=True)
    malformed_transfer = dict(transfer_state)
    malformed_transfer["ownership"] = dict(transfer_state["ownership"])
    malformed_transfer["ownership"]["transfer_from"] = "wrong-owner"
    root, path, _, out, decision = run(malformed_transfer, event_extra={"sessionId": "old-owner"})
    check("malformed transfer -> ownership recovery allow", reason_ok(decision, "allow", "ownership-recovery-required"), out)
    check("malformed transfer leaves state unchanged", state_after(path) == malformed_transfer)
    shutil.rmtree(root, ignore_errors=True)
    malformed_owned = active()
    malformed_owned["ownership"]["transfer_from"] = "stale-owner"
    root, path, _, out, decision = run(malformed_owned)
    check(
        "malformed owned binding -> ownership recovery allow",
        reason_ok(decision, "allow", "ownership-recovery-required"),
        out,
    )
    check("malformed owned binding leaves state unchanged", state_after(path) == malformed_owned)
    shutil.rmtree(root, ignore_errors=True)
    malformed_owned_missing = active()
    del malformed_owned_missing["ownership"]["transfer_from"]
    root, path, _, out, decision = run(malformed_owned_missing)
    check(
        "missing owned transfer binding -> ownership recovery allow",
        reason_ok(decision, "allow", "ownership-recovery-required"),
        out,
    )
    check(
        "missing owned transfer binding leaves state unchanged",
        state_after(path) == malformed_owned_missing,
    )
    shutil.rmtree(root, ignore_errors=True)
    root, path, _, out, decision = run(active(), event_extra={"sessionId": "other-session"})
    check("legacy/identity mismatch does not block", out == "" and decision is None)
    shutil.rmtree(root, ignore_errors=True)
    root, path, _, out, decision = run(active(), event_extra={"sessionId": None})
    check("missing event identity -> recovery allow", reason_ok(decision, "allow", "ownership-recovery-required"), out)
    check("missing event identity leaves state unchanged", state_after(path)["review"].get("consecutive_blocks") is None)
    shutil.rmtree(root, ignore_errors=True)
    legacy = active()
    del legacy["ownership"]
    root, path, _, out, decision = run(legacy)
    check("missing ownership -> recovery allow", reason_ok(decision, "allow", "ownership-recovery-required"), out)
    check("missing ownership leaves state unchanged", state_after(path) == legacy)
    shutil.rmtree(root, ignore_errors=True)

    provenance = {"round": 1, "dispatch_tool_call_id": "call_dispatch", "reviewer_agent_id": "agent-reviewer"}
    genuine = lineage_transcript()
    root, _, _, out, decision = run(lineage_state(provenance=provenance), genuine)
    check("current SHIP lineage -> reconciliation block", reason_ok(decision, "block", "nonce-tagged SHIP verdict marker"), out)
    shutil.rmtree(root, ignore_errors=True)
    request_only = lineage_without_dispatch_observation(genuine, "tool.execution_start")
    root, _, _, out, decision = run(lineage_state(provenance=provenance), request_only)
    check(
        "request-only dispatch observation -> reconciliation block",
        reason_ok(decision, "block", "nonce-tagged SHIP verdict marker"),
        out,
    )
    shutil.rmtree(root, ignore_errors=True)
    start_only = lineage_without_dispatch_observation(genuine, "assistant.message")
    start_only = "\n".join(
        line
        for line in start_only.splitlines()
        if not (
            json.loads(line).get("type") == "assistant.message"
            and "agentId" not in json.loads(line)
        )
    ) + "\n"
    root, _, _, out, decision = run(lineage_state(provenance=provenance), start_only)
    check(
        "start-only dispatch observation -> reconciliation block",
        reason_ok(decision, "block", "nonce-tagged SHIP verdict marker"),
        out,
    )
    shutil.rmtree(root, ignore_errors=True)
    paired = genuine
    root, _, _, out, decision = run(lineage_state(provenance=provenance), paired)
    check(
        "paired dispatch observations -> one reconciliation block",
        reason_ok(decision, "block", "nonce-tagged SHIP verdict marker"),
        out,
    )
    shutil.rmtree(root, ignore_errors=True)
    duplicate_request = duplicate_dispatch_observation(genuine, "assistant.message")
    root, _, _, out, decision = run(lineage_state(provenance=provenance), duplicate_request)
    check(
        "duplicate request observation -> unavailable owner block",
        reason_ok(decision, "block", "review-reconciliation-unavailable"),
        out,
    )
    shutil.rmtree(root, ignore_errors=True)
    duplicate_start = duplicate_dispatch_observation(genuine, "tool.execution_start")
    root, _, _, out, decision = run(lineage_state(provenance=provenance), duplicate_start)
    check(
        "duplicate start observation -> unavailable owner block",
        reason_ok(decision, "block", "review-reconciliation-unavailable"),
        out,
    )
    shutil.rmtree(root, ignore_errors=True)
    in_flight = "\n".join(
        line
        for line in genuine.splitlines()
        if json.loads(line).get("type") != "subagent.completed"
    ) + "\n"
    root, _, _, out, decision = run(lineage_state(provenance=provenance), in_flight)
    check(
        "in-flight dispatch without completion -> ordinary pending block",
        reason_ok(decision, "block", "review loop active") and "review-reconciliation-unavailable" not in decision["reason"],
        out,
    )
    shutil.rmtree(root, ignore_errors=True)
    root, _, _, out, decision = run(
        lineage_state(provenance=provenance),
        lineage_transcript(verdict="FIX-FIRST", critical_high="true"),
    )
    check("current FIX-FIRST lineage -> reconciliation block", reason_ok(decision, "block", "nonce-tagged FIX-FIRST verdict marker"), out)
    shutil.rmtree(root, ignore_errors=True)
    stale_round = lineage_state(
        provenance={
            "round": 1,
            "dispatch_tool_call_id": "call_dispatch",
            "reviewer_agent_id": "agent-reviewer",
        }
    )
    stale_round["review"]["round"] = 2
    root, _, _, out, decision = run(stale_round, genuine)
    check(
        "stale provenance round -> ordinary owner block",
        reason_ok(decision, "block", "review-reconciliation-unavailable"),
        out,
    )
    shutil.rmtree(root, ignore_errors=True)
    malformed_provenance = lineage_state(
        provenance={"round": 1, "dispatch_tool_call_id": "call_dispatch"}
    )
    root, _, _, out, decision = run(malformed_provenance, genuine)
    check(
        "missing reviewer provenance -> ordinary owner block",
        reason_ok(decision, "block", "review-reconciliation-unavailable"),
        out,
    )
    shutil.rmtree(root, ignore_errors=True)
    ordinary_tool_events = (
        genuine.replace(
            "\n{\"type\": \"subagent.completed\"",
            "\n"
            + json.dumps(
                {
                    "type": "assistant.message",
                    "data": {
                        "toolRequests": [
                            {"toolCallId": "call_parent_tool", "name": "view"}
                        ]
                    },
                }
            )
            + "\n"
            + json.dumps(
                {
                    "type": "tool.execution_start",
                    "data": {"toolCallId": "call_parent_tool"},
                }
            )
            + "\n{\"type\": \"subagent.completed\"",
        )
        .replace(
            "\n{\"type\": \"subagent.completed\"",
            "\n"
            + json.dumps(
                {
                    "type": "tool.execution_start",
                    "data": {"toolCallId": "call_child_tool"},
                }
            )
            + "\n{\"type\": \"subagent.completed\"",
            1,
        )
    )
    root, _, _, out, decision = run(lineage_state(provenance=provenance), ordinary_tool_events)
    check(
        "ordinary parent and child tools do not invalidate current lineage",
        reason_ok(decision, "block", "nonce-tagged SHIP verdict marker"),
        out,
    )
    shutil.rmtree(root, ignore_errors=True)
    false_positive_transcripts = [
        ("quoted marker", lineage_transcript(content_prefix='> VERDICT: SHIP [a1b2c3d4]')),
        ("fenced marker", lineage_transcript(content_prefix="```")),
        (
            "duplicate marker",
            lineage_transcript(content_prefix="VERDICT: SHIP [a1b2c3d4]\nhas_critical_or_high: false"),
        ),
        ("trailing content", lineage_transcript(trailing="\nextra text")),
        ("wrong nonce", lineage_transcript(nonce="deadbeef")),
        (
            "wrong reviewer lineage",
            lineage_transcript().replace('"agentId": "agent-reviewer"', '"agentId": "agent-other"'),
        ),
        (
            "second dispatch id",
            lineage_transcript().replace(
                '\n{"type": "subagent.completed"',
                '\n'
                + json.dumps(
                    {
                        "type": "subagent.started",
                        "agentId": "agent-other",
                        "data": {
                            "toolCallId": "call_other",
                            "agentName": "adversary",
                        },
                    }
                )
                + '\n{"type": "subagent.completed"',
            ),
        ),
    ]
    for label, transcript in false_positive_transcripts:
        root, _, _, out, decision = run(lineage_state(provenance=provenance), transcript)
        check("%s -> ordinary owner block" % label, reason_ok(decision, "block", "review-reconciliation-unavailable"), out)
        shutil.rmtree(root, ignore_errors=True)
    tool_result = genuine.replace('"type": "assistant.message"', '"type": "tool.execution_complete"')
    root, _, _, out, decision = run(lineage_state(provenance=provenance), tool_result)
    check("tool result marker -> ordinary owner block", reason_ok(decision, "block", "review-reconciliation-unavailable"), out)
    shutil.rmtree(root, ignore_errors=True)
    stale = lineage_transcript(dispatch="call_stale")
    root, _, _, out, decision = run(lineage_state(provenance=provenance), stale)
    check("stale dispatch -> ordinary owner block", reason_ok(decision, "block", "review-reconciliation-unavailable"), out)
    shutil.rmtree(root, ignore_errors=True)
    large_prefix = "".join(json.dumps({"type": "noise", "data": "x" * 1024}) + "\n" for _ in range(300))
    root, _, _, out, decision = run(lineage_state(provenance=provenance), large_prefix + genuine)
    check("streamed lineage beyond 256 KiB -> reconciliation block", reason_ok(decision, "block", "nonce-tagged SHIP verdict marker"), out)
    shutil.rmtree(root, ignore_errors=True)
    unrelated_prefix = "".join(
        json.dumps(
            {
                "type": "assistant.message",
                "data": {
                    "toolRequests": [
                        {"toolCallId": "unrelated-%d" % index, "name": "view"}
                    ],
                    "content": "unrelated " + ("x" * 4096),
                },
            }
        )
        + "\n"
        for index in range(2000)
    )
    root, _, _, out, decision = run(lineage_state(provenance=provenance), unrelated_prefix + genuine)
    check(
        "many unrelated records and content retain current lineage",
        reason_ok(decision, "block", "nonce-tagged SHIP verdict marker"),
        out,
    )
    shutil.rmtree(root, ignore_errors=True)
    root, _, _, out, decision = run(active(verdict="PENDING"), genuine)
    check("missing provenance -> ordinary pending block", reason_ok(decision, "block", "review loop active"), out)
    check("missing provenance has no unavailable marker", "review-reconciliation-unavailable" not in decision["reason"])
    shutil.rmtree(root, ignore_errors=True)
    exhausted = active()
    exhausted["review"]["active"] = False
    exhausted["review"]["verdict"] = "PENDING"
    exhausted["review"]["recovery"] = {
        "status": "reconciliation_exhausted",
        "attempts": 1,
        "marker": "review-reconciliation-unavailable",
    }
    root, path, _, out, decision = run(exhausted)
    check("exhausted reconciliation -> diagnostic allow", reason_ok(decision, "allow", "review-reconciliation-unavailable"), out)
    check("exhausted reconciliation leaves state unchanged", state_after(path) == exhausted)
    shutil.rmtree(root, ignore_errors=True)
    malformed_exhaustion_cases = [
        ("active review", {"active": True, "verdict": "PENDING", "attempts": 1}),
        ("SHIP verdict", {"active": False, "verdict": "SHIP", "attempts": 1}),
        ("zero attempts", {"active": False, "verdict": "PENDING", "attempts": 0}),
        ("two attempts", {"active": False, "verdict": "PENDING", "attempts": 2}),
        ("wrong marker", {"active": False, "verdict": "PENDING", "attempts": 1, "marker": "wrong"}),
    ]
    for label, fields in malformed_exhaustion_cases:
        malformed = active()
        malformed["review"].update(
            {
                "active": fields["active"],
                "verdict": fields["verdict"],
                "recovery": {
                    "status": "reconciliation_exhausted",
                    "attempts": fields["attempts"],
                    "marker": fields.get("marker", "review-reconciliation-unavailable"),
                },
            }
        )
        root, _, _, out, decision = run(malformed)
        check(
            "malformed exhausted %s -> ordinary owner enforcement" % label,
            reason_ok(decision, "block", "review-reconciliation-unavailable"),
            out,
        )
        shutil.rmtree(root, ignore_errors=True)

    print("additional allow paths")
    root, _, _, _, decision = run(active(verdict="PENDING", round_=1, consecutive=7), "VERDICT: SHIP [a1b2c3d4]\n")
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
