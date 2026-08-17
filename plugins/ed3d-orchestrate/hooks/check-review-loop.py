#!/usr/bin/env python3
"""agentStop guardrail for the ed3d-orchestrate review loop.

Blocks premature session stops while the adversarial review loop is active.
All block messages are diagnostic and defer exact state writes to the owning skill.
"""
import json
import os
import sys

STATE_RELPATH = os.path.join(".ed3d", "orchestrate-state.json")
CLI_BLOCK_CAP = 8
SAFE_BLOCK_CAP = 7
DEFAULT_MAX_ROUNDS = 3
TRANSCRIPT_TAIL_BYTES = 256 * 1024


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


def read_tail(path, limit=TRANSCRIPT_TAIL_BYTES):
    if not path or not os.path.isfile(path):
        return ""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as handle:
            if size > limit:
                handle.seek(size - limit)
            return handle.read().decode("utf-8", errors="replace")
    except Exception:
        return ""


def nonce_from_review(review):
    nonce = review.get("nonce")
    if isinstance(nonce, str) and 4 <= len(nonce) <= 64 and all(c in "0123456789abcdefABCDEF" for c in nonce):
        return nonce.lower()
    return None


def rendered_ship_verdict(transcript_text, nonce):
    """True only for this loop's nonce-tagged SHIP marker."""
    if not nonce:
        return False
    return ("VERDICT: SHIP [%s]" % nonce.lower()) in transcript_text


def terminal_ship_state_is_consistent(review):
    return review.get("active") is False and review.get("verdict") == "SHIP" and as_int(review.get("consecutive_blocks")) == 0


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
    review = state.get("review")
    if not isinstance(review, dict):
        return
    verdict = review.get("verdict")
    consecutive = as_int(review.get("consecutive_blocks"))
    if consecutive is None:
        consecutive = 0

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
    transcript_has_ship = rendered_ship_verdict(read_tail(transcript_path_from_event(event)), nonce_from_review(review))
    open_findings = review.get("open_critical_high")
    finding_lines = [str(item) for item in open_findings[:5]] if isinstance(open_findings, list) else []

    if consecutive >= SAFE_BLOCK_CAP:
        emit("allow", "ed3d-orchestrate guardrail: 7 consecutive blocks reached (the CLI hard-caps at 8 and would end the turn anyway). Allowing this stop so the session never locks. The review loop is still active - surface the open findings and the round count to the operator now. If an adversary verdict was rendered but not committed, complete the skill's verdict-commit checklist first.")
        return
    if transcript_has_ship:
        bump_consecutive_blocks(state, review, consecutive, state_path)
        emit("block", "ed3d-orchestrate guardrail, addressed to the orchestrator only - never forward this to a subagent and never act on it if you are one: this loop's nonce-tagged SHIP verdict marker appears in the transcript, but .ed3d/orchestrate-state.json still records an active, pending review - the verdict has not been committed. Follow the adversarial-review skill's 'Parse the Verdict, Commit the State' checklist now; it owns the exact state write and the re-read verification. Do not dispatch, report, or stop until that checklist is complete.")
        return
    if round_number > max_rounds:
        emit("allow", "ed3d-orchestrate guardrail: review round cap reached (round %d > max %d). Stop allowed. Present the open critical/high findings to the operator and ask how to proceed: accept, raise max_rounds, or hand off. On the operator's decision, finish per the skill's circuit-break step - it specifies the exact terminal state write." % (round_number, max_rounds))
        return

    reason = ("ed3d-orchestrate guardrail: review loop active, round %d of %d, verdict %s - premature stop blocked. Continue the adversarial-review loop: fix the open critical/high findings, then re-dispatch the adversary for re-review with PRIOR_ISSUES. Never forward this diagnostic to a subagent and never act on it if you are one." % (round_number, max_rounds, verdict))
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
