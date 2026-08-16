#!/usr/bin/env python3
"""agentStop guardrail for the ed3d-orchestrate review loop.

Blocks premature session stops while the adversarial review loop is active,
so the tumble dryer cannot be walked away from mid-loop.

Protocol (per the GitHub Copilot hooks reference):
- Event JSON arrives on stdin. The native `agentStop` payload (camelCase keys)
  and the VS Code-compatible `Stop` payload (PascalCase event name) both carry
  `cwd` and `stop_hook_active`, which are the only fields used here.
- A single decision JSON goes to stdout:
  {"decision": "block", "reason": "..."}  forces another turn
  {"decision": "allow", "reason": "..."}  permits the stop (informational)
- After 8 consecutive `block` decisions the CLI overrides the hook and ends
  the turn regardless; we stop blocking at 7 so the session never hard-locks.
- Fail-open everywhere: missing state file, malformed JSON, unreadable state,
  or any internal error exits 0 with no output. Hook timeouts also fail open.

State file: `.ed3d/orchestrate-state.json`, located by walking up from the
event's `cwd`. Maintained by the orchestrating-the-loop skill; this hook only
ever increments `review.consecutive_blocks` (best-effort).
"""
import json
import os
import sys

STATE_RELPATH = os.path.join(".ed3d", "orchestrate-state.json")
CLI_BLOCK_CAP = 8      # CLI overrides the hook after 8 consecutive blocks
SAFE_BLOCK_CAP = 7     # we allow at 7 so the hard cap is never reached
DEFAULT_MAX_ROUNDS = 3


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
    if not isinstance(review, dict) or review.get("active") is not True:
        return

    verdict = review.get("verdict")
    if verdict == "SHIP":
        return  # final verdict; allow silently

    round_number = as_int(review.get("round"))
    if round_number is None:
        return  # malformed round counter -> fail open
    max_rounds = as_int(review.get("max_rounds"))
    if max_rounds is None:
        max_rounds = DEFAULT_MAX_ROUNDS
    consecutive = as_int(review.get("consecutive_blocks"))
    if consecutive is None:
        consecutive = 0
    stop_hook_active = event.get("stop_hook_active") is True

    open_findings = review.get("open_critical_high")
    finding_lines = []
    if isinstance(open_findings, list):
        finding_lines = [str(item) for item in open_findings[:5]]

    if consecutive >= SAFE_BLOCK_CAP:
        emit(
            "allow",
            "ed3d-orchestrate guardrail: 7 consecutive blocks reached (the CLI "
            "hard-caps at 8 and would end the turn anyway). Allowing this stop so "
            "the session never locks. The review loop is still active - surface "
            "the open findings and the round count to the operator now.",
        )
        return

    if round_number > max_rounds:
        emit(
            "allow",
            "ed3d-orchestrate guardrail: review round cap reached (round %d > max "
            "%d). Stop allowed. Present the open critical/high findings to the "
            "operator and ask how to proceed: accept, raise max_rounds, or hand "
            "off. On acceptance, set review.active=false and verdict=SHIP in "
            ".ed3d/orchestrate-state.json." % (round_number, max_rounds),
        )
        return

    reason = (
        "ed3d-orchestrate guardrail: review loop active, round %d of %d, verdict "
        "%s - premature stop blocked. Continue the adversarial-review loop: fix "
        "the open critical/high findings, then re-dispatch the adversary for "
        "re-review with PRIOR_ISSUES." % (round_number, max_rounds, verdict)
    )
    if finding_lines:
        reason += " Open findings: " + "; ".join(finding_lines) + "."
    if stop_hook_active:
        reason += (
            " (Note: this continuation was already forced by a prior block; if no "
            "progress is possible, circuit-break: set round = max_rounds + 1 and "
            "ask the operator to decide.)"
        )

    # Best-effort consecutive-block tracking; the decision stands even if the
    # state file cannot be rewritten.
    try:
        review["consecutive_blocks"] = consecutive + 1
        tmp_path = state_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump(state, handle, indent=2)
            handle.write("\n")
        os.replace(tmp_path, state_path)
    except Exception:
        pass

    emit("block", reason)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # fail open, always
    sys.exit(0)
