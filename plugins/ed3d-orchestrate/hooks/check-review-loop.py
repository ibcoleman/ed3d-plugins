#!/usr/bin/env python3
"""agentStop guardrail for the ed3d-orchestrate review loop.

The hook is an imperative shell around conservative, bounded transcript
reconciliation.  Parent stop decisions are scoped to the persisted owner;
the child write guard remains review-wide because preToolUse has no parent
owner identity.
"""
# pattern: Mixed (unavoidable)
import json
import os
import re
import sys

STATE_RELPATH = os.path.join(".ed3d", "orchestrate-state.json")
CLI_BLOCK_CAP = 8
SAFE_BLOCK_CAP = 7
DEFAULT_MAX_ROUNDS = 3

RECOVERY_OWNERSHIP = "ownership-recovery-required"
RECOVERY_RECONCILIATION = "review-reconciliation-unavailable"
ADVERSARY_NAMES = {"adversary", "ed3d-orchestrate:adversary"}


def emit(decision, reason):
    print(json.dumps({"decision": decision, "reason": reason}))


def as_int(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


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


def transcript_path_from_event(event):
    path = event.get("transcriptPath") or event.get("transcript_path")
    return path if isinstance(path, str) and path else None


def nonce_from_review(review):
    nonce = review.get("nonce")
    if isinstance(nonce, str) and 4 <= len(nonce) <= 64 and all(
        c in "0123456789abcdefABCDEF" for c in nonce
    ):
        return nonce.lower()
    return None


def event_session_id(event):
    for key in ("sessionId", "session_id"):
        value = event.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def recovery_allow(reason):
    emit("allow", "ed3d-orchestrate %s: %s; state was not changed." % (RECOVERY_OWNERSHIP, reason))


def owner_outcome(state, event):
    """Return ``owner``, ``silent``, or ``recovery`` without changing state."""
    ownership = state.get("ownership")
    if not isinstance(ownership, dict):
        return "recovery"
    status = ownership.get("status")
    live_id = event_session_id(event)
    if not live_id:
        return "recovery"
    if status == "owned":
        owner_id = ownership.get("session_id")
        if not isinstance(owner_id, str) or not owner_id:
            return "recovery"
        return "owner" if live_id == owner_id else "silent"
    if status == "transfer_pending":
        owner_id = ownership.get("session_id")
        transfer_from = ownership.get("transfer_from")
        if (
            not isinstance(owner_id, str)
            or not owner_id
            or not isinstance(transfer_from, str)
            or transfer_from != owner_id
        ):
            return "recovery"
        return "transfer_owner" if live_id == owner_id else "silent"
    if status == "recovery_required":
        return "recovery"
    return "recovery"


def terminal_ship_state_is_consistent(review):
    return (
        review.get("active") is False
        and review.get("verdict") == "SHIP"
        and as_int(review.get("consecutive_blocks")) == 0
    )


def exhausted_recovery_is_consistent(review):
    recovery = review.get("recovery")
    return (
        isinstance(recovery, dict)
        and recovery.get("status") == "reconciliation_exhausted"
        and recovery.get("marker") == RECOVERY_RECONCILIATION
        and as_int(recovery.get("attempts")) == 1
        and review.get("active") is False
        and review.get("verdict") == "PENDING"
    )


def bump_consecutive_blocks(state, review, consecutive, state_path):
    try:
        review["consecutive_blocks"] = consecutive + 1
        tmp_path = state_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump(state, handle, indent=2)
            handle.write("\n")
        os.replace(tmp_path, state_path)
    except Exception:
        pass


def _tool_call_ids(event):
    data = event.get("data")
    if not isinstance(data, dict):
        return []
    requests = data.get("toolRequests")
    if not isinstance(requests, list):
        return []
    return [
        request.get("toolCallId")
        for request in requests
        if isinstance(request, dict) and isinstance(request.get("toolCallId"), str)
    ]


def _data_tool_call_id(event):
    data = event.get("data")
    if isinstance(data, dict) and isinstance(data.get("toolCallId"), str):
        return data["toolCallId"]
    return None


def _terminal_verdict(content, nonce):
    if not isinstance(content, str) or not nonce:
        return None
    lines = content.splitlines()
    while lines and not lines[-1].strip():
        lines.pop()
    if len(lines) < 2:
        return None
    if any(
        line.strip().startswith((">", "```", "~~~")) or "```" in line
        for line in lines
    ):
        return None
    verdict_pattern = re.compile(r"^VERDICT: (SHIP|FIX-FIRST) \[([0-9a-fA-F]+)\]$")
    boolean_pattern = re.compile(r"^has_critical_or_high: (true|false)$")
    verdict_lines = [line for line in lines if verdict_pattern.fullmatch(line)]
    boolean_lines = [line for line in lines if boolean_pattern.fullmatch(line)]
    if len(verdict_lines) != 1 or len(boolean_lines) != 1:
        return None
    verdict_match = verdict_pattern.fullmatch(lines[-2])
    boolean_match = boolean_pattern.fullmatch(lines[-1])
    if not verdict_match or not boolean_match:
        return None
    if verdict_match.group(2).lower() != nonce:
        return None
    verdict = verdict_match.group(1)
    boolean_value = boolean_match.group(1)
    if (verdict == "SHIP") != (boolean_value == "false"):
        return None
    return verdict


def _provenance_status(review):
    """Classify the optional reviewer binding without weakening enforcement."""
    provenance = review.get("provenance")
    if provenance is None:
        return "missing"
    if not isinstance(provenance, dict):
        return "invalid"
    if as_int(provenance.get("round")) != as_int(review.get("round")):
        return "invalid"
    if not isinstance(provenance.get("dispatch_tool_call_id"), str) or not provenance.get(
        "dispatch_tool_call_id"
    ):
        return "invalid"
    if not isinstance(provenance.get("reviewer_agent_id"), str) or not provenance.get(
        "reviewer_agent_id"
    ):
        return "invalid"
    return "valid"


def reconcile_transcript(path, review):
    """Return ``SHIP``/``FIX-FIRST``, ``unavailable``, or ``None``.

    Only fixed-size IDs, flags, and the latest reviewer message are retained.
    The file is consumed from the beginning so results beyond the old tail
    limit remain visible without retaining the transcript.
    """
    nonce = nonce_from_review(review)
    provenance_status = _provenance_status(review)
    if provenance_status == "missing" or not nonce:
        return None
    if provenance_status != "valid":
        return "unavailable"
    provenance = review["provenance"]
    dispatch_id = provenance.get("dispatch_tool_call_id")
    reviewer_id = provenance.get("reviewer_agent_id")
    if not path or not os.path.isfile(path):
        return "unavailable"

    assistant_dispatch_ids = set()
    start_dispatch_ids = set()
    candidate_started = False
    candidate_completed = False
    candidate_invalid = False
    latest_message = None

    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            for raw_line in handle:
                try:
                    event = json.loads(raw_line)
                except Exception:
                    continue
                if not isinstance(event, dict):
                    continue
                event_type = event.get("type")
                if event_type == "assistant.message":
                    agent_id = event.get("agentId")
                    if agent_id is None:
                        ids = _tool_call_ids(event)
                        assistant_dispatch_ids.update(ids)
                    elif agent_id == reviewer_id:
                        data = event.get("data")
                        content = data.get("content") if isinstance(data, dict) else None
                        if candidate_started and not candidate_completed:
                            latest_message = content
                        elif candidate_completed:
                            candidate_invalid = True
                elif event_type == "tool.execution_start":
                    tool_call_id = _data_tool_call_id(event)
                    if tool_call_id:
                        start_dispatch_ids.add(tool_call_id)
                elif event_type == "subagent.started":
                    tool_call_id = _data_tool_call_id(event)
                    agent_id = event.get("agentId")
                    data = event.get("data")
                    agent_name = data.get("agentName") if isinstance(data, dict) else None
                    if tool_call_id == dispatch_id:
                        if candidate_started:
                            candidate_invalid = True
                        if (
                            dispatch_id in assistant_dispatch_ids
                            and dispatch_id in start_dispatch_ids
                            and agent_id == reviewer_id
                            and agent_name in ADVERSARY_NAMES
                        ):
                            candidate_started = True
                        else:
                            candidate_invalid = True
                    elif (
                        candidate_started
                        and agent_name in ADVERSARY_NAMES
                        and isinstance(tool_call_id, str)
                    ):
                        # Only a second adversary dispatch competes with the
                        # current reviewer.  Ordinary parent/child tools are
                        # unrelated transcript activity and must not poison a
                        # genuine completion chain.
                        candidate_invalid = True
                elif event_type == "subagent.completed":
                    tool_call_id = _data_tool_call_id(event)
                    agent_id = event.get("agentId")
                    if tool_call_id == dispatch_id and agent_id == reviewer_id:
                        if candidate_completed or not candidate_started:
                            candidate_invalid = True
                        candidate_completed = True
    except Exception:
        return "unavailable"

    if (
        candidate_started
        and candidate_completed
        and not candidate_invalid
        and latest_message is not None
    ):
        verdict = _terminal_verdict(latest_message, nonce)
        return verdict if verdict else "unavailable"
    return "unavailable"


def main():
    raw = sys.stdin.read()
    try:
        event = json.loads(raw) if raw.strip() else {}
    except Exception:
        return
    if not isinstance(event, dict):
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
    if not isinstance(state, dict):
        return
    ownership_result = owner_outcome(state, event)
    if ownership_result == "silent":
        return
    if ownership_result == "transfer_owner":
        emit(
            "allow",
            "ed3d-orchestrate transfer-pending: the recorded owner may stop "
            "while the explicit resume claim is pending; state was not changed.",
        )
        return
    if ownership_result == "recovery":
        recovery_allow("the live or persisted owner identity is missing or invalid")
        return

    review = state.get("review")
    if not isinstance(review, dict):
        return
    verdict = review.get("verdict")
    consecutive = as_int(review.get("consecutive_blocks"))
    if consecutive is None:
        consecutive = 0

    recovery = review.get("recovery")
    if isinstance(recovery, dict) and recovery.get("status") == "reconciliation_exhausted" and exhausted_recovery_is_consistent(review):
        emit(
            "allow",
            "ed3d-orchestrate review-reconciliation-unavailable: reconciliation "
            "is exhausted; no verdict exists and an explicit operator choice is required.",
        )
        return
    if isinstance(recovery, dict) and recovery.get("status") == "reconciliation_exhausted":
        if consecutive >= SAFE_BLOCK_CAP:
            emit(
                "allow",
                "ed3d-orchestrate guardrail: 7 consecutive blocks reached while "
                "reconciliation-exhausted metadata is inconsistent; stop allowed "
                "only for the CLI safety cap and no verdict is inferred.",
            )
            return
        bump_consecutive_blocks(state, review, consecutive, state_path)
        emit(
            "block",
            "ed3d-orchestrate guardrail: review-reconciliation-unavailable: "
            "reconciliation_exhausted metadata is inconsistent; keep ordinary "
            "owner enforcement and repair the recovery state without claiming "
            "a verdict.",
        )
        return

    if verdict == "SHIP":
        if terminal_ship_state_is_consistent(review):
            return
        if consecutive >= SAFE_BLOCK_CAP:
            emit("allow", "ed3d-orchestrate guardrail: 7 consecutive blocks reached with an inconsistent final SHIP state (review.active / verdict / consecutive_blocks mismatch). Allowing this stop so the session never locks; the terminal state is wrong - run the adversarial-review skill's terminal-state verification and repair the state file per its checklist before starting another loop.")
            return
        bump_consecutive_blocks(state, review, consecutive, state_path)
        emit("block", "ed3d-orchestrate guardrail, addressed to the orchestrator only: the state file records a final SHIP verdict but its terminal fields are internally inconsistent (review.active / verdict / consecutive_blocks disagree). Never forward this diagnostic to a subagent and never act on it if you are one. Re-run the terminal-state verification from the adversarial-review skill and repair the state file exactly as that checklist specifies before stopping.")
        return

    if review.get("active") is not True:
        return
    round_number = as_int(review.get("round"))
    if round_number is None:
        return
    max_rounds = as_int(review.get("max_rounds"))
    if max_rounds is None:
        max_rounds = DEFAULT_MAX_ROUNDS
    stop_hook_active = event.get("stop_hook_active") is True
    reconciliation = reconcile_transcript(
        transcript_path_from_event(event), review
    )
    open_findings = review.get("open_critical_high")
    finding_lines = [str(item) for item in open_findings[:5]] if isinstance(open_findings, list) else []

    if consecutive >= SAFE_BLOCK_CAP:
        emit("allow", "ed3d-orchestrate guardrail: 7 consecutive blocks reached (the CLI hard-caps at 8 and would end the turn anyway). Allowing this stop so the session never locks. The review loop is still active - surface the open findings and the round count to the operator now. If an adversary verdict was rendered but not committed, complete the skill's verdict-commit checklist first.")
        return
    if reconciliation in {"SHIP", "FIX-FIRST"}:
        bump_consecutive_blocks(state, review, consecutive, state_path)
        emit("block", "ed3d-orchestrate guardrail, addressed to the orchestrator only - never forward this to a subagent and never act on it if you are one: this loop's nonce-tagged %s verdict marker appears in the transcript, but .ed3d/orchestrate-state.json still records an active, pending review - the verdict has not been committed. Follow the adversarial-review skill's 'Parse the Verdict, Commit the State' checklist now; it owns the exact state write and the re-read verification. Do not dispatch, report, or stop until that checklist is complete." % reconciliation)
        return
    if round_number > max_rounds:
        emit("allow", "ed3d-orchestrate guardrail: review round cap reached (round %d > max %d). Stop allowed. Present the open critical/high findings to the operator and ask how to proceed: accept, raise max_rounds, or hand off. On the operator's decision, finish per the skill's circuit-break step - it specifies the exact terminal state write." % (round_number, max_rounds))
        return

    reason = ("ed3d-orchestrate guardrail: review loop active, round %d of %d, verdict %s - premature stop blocked. Continue the adversarial-review loop: fix the open critical/high findings, then re-dispatch the adversary for re-review with PRIOR_ISSUES. Never forward this diagnostic to a subagent and never act on it if you are one." % (round_number, max_rounds, verdict))
    if reconciliation == "unavailable":
        reason += " review-reconciliation-unavailable: completed reviewer lineage could not be proven; keep owner enforcement and use the bounded resume re-arm procedure."
    if finding_lines:
        reason += " Open findings: " + "; ".join(finding_lines) + "."
    if stop_hook_active:
        reason += " (Note: this continuation was already forced by a prior block; if no progress is possible, use the adversarial-review skill's circuit-break step - it owns the exact state write and the operator decision.)"
    bump_consecutive_blocks(state, review, consecutive, state_path)
    emit("block", reason)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
