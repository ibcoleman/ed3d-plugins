#!/usr/bin/env python3
"""agentStop guardrail for the ed3d-orchestrate review loop.

Blocks premature session stops while the adversarial review loop is active,
so the tumble dryer cannot be walked away from mid-loop.

Protocol (per the GitHub Copilot hooks reference):
- Event JSON arrives on stdin. The native `agentStop` payload (camelCase keys)
  and the VS Code-compatible `Stop` payload (PascalCase event name) both carry
  `cwd` and `stop_hook_active`. When available, `transcriptPath` / `transcript_path`
  is scanned for already-rendered adversary verdicts that have not reached the
  state file yet.
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
    if isinstance(path, str) and path:
        return path
    return None


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


def rendered_ship_verdict(transcript_text):
    return "VERDICT: SHIP" in transcript_text and "has_critical_or_high: false" in transcript_text


def terminal_ship_state_is_consistent(review):
    return review.get("active") is False and review.get("verdict") == "SHIP" and as_int(review.get("consecutive_blocks")) == 0


def bump_consecutive_blocks(state, review, consecutive, state_path):
    """Best-effort increment; the decision stands even if the rewrite fails."""
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
            return  # final verdict; allow silently
        if consecutive >= SAFE_BLOCK_CAP:
            emit(
                "allow",
                "ed3d-orchestrate guardrail: 7 consecutive blocks reached with an "
                "inconsistent final SHIP state (review.active / verdict / "
                "consecutive_blocks mismatch). Allowing this stop so the session "
                "never locks, but the audit trail is wrong - repair "
                ".ed3d/orchestrate-state.json (active=false, verdict=SHIP, "
                "consecutive_blocks=0) before starting another loop.",
            )
            return
        bump_consecutive_blocks(state, review, consecutive, state_path)
        emit(
            "block",
            "ed3d-orchestrate guardrail: final SHIP state is inconsistent. "
            "Before stopping, rewrite .ed3d/orchestrate-state.json so "
            "review.active=false, verdict=SHIP, and consecutive_blocks=0; "
            "then re-read the state file and report.",
        )
        return

    if review.get("active") is not True:
        return

    round_number = as_int(review.get("round"))
    if round_number is None:
        return  # malformed round counter -> fail open
    max_rounds = as_int(review.get("max_rounds"))
    if max_rounds is None:
        max_rounds = DEFAULT_MAX_ROUNDS
    stop_hook_active = event.get("stop_hook_active") is True
    transcript_text = read_tail(transcript_path_from_event(event))
    transcript_has_ship = rendered_ship_verdict(transcript_text)

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
            "the open findings and the round count to the operator now. If an "
            "adversary verdict was already rendered, commit it to the state file "
            "first, including consecutive_blocks=0.",
        )
        return

    if transcript_has_ship:
        bump_consecutive_blocks(state, review, consecutive, state_path)
        emit(
            "block",
            "ed3d-orchestrate guardrail: adversary already rendered VERDICT: SHIP, "
            "but .ed3d/orchestrate-state.json still says PENDING/active. Do not "
            "dispatch, report, or stop. Commit the verdict to the state file now: "
            "review.active=false, verdict=SHIP, open_critical_high=[], "
            "consecutive_blocks=0, and append the round's review.history entry. "
            "Then re-read the state file before stopping.",
        )
        return

    if round_number > max_rounds:
        emit(
            "allow",
            "ed3d-orchestrate guardrail: review round cap reached (round %d > max "
            "%d). Stop allowed. Present the open critical/high findings to the "
            "operator and ask how to proceed: accept, raise max_rounds, or hand "
            "off. On acceptance, set review.active=false, verdict=SHIP, and "
            "consecutive_blocks=0 in .ed3d/orchestrate-state.json." % (round_number, max_rounds),
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

    bump_consecutive_blocks(state, review, consecutive, state_path)

    emit("block", reason)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # fail open, always
    sys.exit(0)
