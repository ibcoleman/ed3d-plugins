---
name: "adversarial-review"
description: "The tumble dryer loop. Dispatches the adversary agent against a commit range, parses its verdict, and cycles fix -> re-review until no critical/high findings remain or max rounds (default 3) is hit, then circuit-breaks to the operator. Updates .ed3d/orchestrate-state.json at every round transition."
user-invocable: false
---

# Adversarial Review (Tumble Dryer)

Drive adversarial review rounds over completed implementation work. This skill is the loop; the `adversary` agent (ed3d-orchestrate) is the reviewer.

**Do not use nested subagents.** You dispatch the adversary and the bug fixer. They must not dispatch subagents; they return directly to you.

## Preconditions

- Implementation work is complete and committed.
- You know `BASE_SHA` (before the work) and `HEAD_SHA` (after), and both are valid commits in the current git repository. If either SHA is missing or invalid, stop and fix the orchestration state — do not dispatch the adversary.
- `.ed3d/orchestrate-state.json` exists and `review.active` is `true`. If it doesn't exist, create the review block before starting:

```json
"review": {
  "active": true,
  "round": 1,
  "max_rounds": 3,
  "verdict": "PENDING",
  "open_critical_high": [],
  "consecutive_blocks": 0,
  "history": [],
  "nonce": "a1b2c3d4"
}
```

Whenever a review arms — including re-arming an existing inactive review block for a new loop — generate a fresh nonce: 8 lowercase hex characters, written as `review.nonce`, overwriting any prior value. Include it in every adversary dispatch as `NONCE: <value>` — the guardrail hook matches rendered verdicts by this tag, which is what keeps the literal `VERDICT: SHIP` strings in skill and agent prose from being mistaken for a real verdict (that false match fabricated a terminal SHIP live on 2026-08-16). Never reuse a nonce across loops.

- **Resume reconciliation.** If resuming into an active review (`review.active: true` on resume), reconcile first: any verdict already rendered in this session's transcript but absent from the state file must be written to the state file before any new dispatch. Do not dispatch a fresh adversary to "check" a verdict the transcript already contains. (This recovers same-session omissions only — after `/clear` the transcript is gone, the state file is the sole truth, and a stale `PENDING` on an already-completed loop can then only be caught by the operator or the round history.)

`max_rounds` defaults to 3; the operator can change it in the state file at any time.

`review.history` is the append-only round record (create the array if the state file predates it — in-flight 0.2.x state files do):

```json
"history": [
  {"round": 1, "verdict": "FIX-FIRST", "critical_high": 1, "advisory": 6},
  {"round": 2, "verdict": "SHIP", "critical_high": 0, "advisory": 0}
]
```

`critical_high` / `advisory` are the counts of findings at those severities in that round's report. Entries are append-only — never rewrite prior entries. An optional `note` string is the entry schema's only sanctioned extension point; no other keys. Rounds legitimately split across `/clear`+resume session boundaries, so per-session dispatch counts undercount the loop; `history` is the authoritative round count for the final report. The round count is the highest `round` value in `history`, not its length — a round can legitimately hold more than one entry (a protocol-failure `PENDING` followed by that round's actual verdict).

## The Loop

### 1. Dispatch the Adversary

Use the account's Auto/default model selection for this dispatch. Do not select a model or set an effort override; the account's CLI defaults decide both.

Dispatch `adversary` (ed3d-orchestrate) without model or effort parameters, and:

```
WHAT_WAS_IMPLEMENTED: [summary of the work]
PLAN_OR_REQUIREMENTS: [absolute path to the plan document]
BASE_SHA: [sha]
HEAD_SHA: [sha]
NONCE: [review.nonce - append it in square brackets to your VERDICT line]
[Round 2+:]
PRIOR_ISSUES:
[verbatim list of open findings from the previous round]
```

**Print the adversary's full response** immediately after committing the verdict to the state file (step 2), before branching on it.

### 2. Parse the Verdict, Commit the State

From the response, extract:

- `VERDICT: SHIP` or `VERDICT: FIX-FIRST` — the rendered line carries the loop nonce as a bracketed suffix (`VERDICT: SHIP [nonce]`); strip the tag when parsing
- `has_critical_or_high: true|false`
- The findings list

Then **immediately, in the same assistant turn**, rewrite `.ed3d/orchestrate-state.json`. Use this checklist and do not skip the re-read:

1. Set `verdict` to the parsed verdict.
2. Set `open_critical_high` to the list of open critical/high finding one-liners.
3. Set `consecutive_blocks: 0` — the guardrail hook increments that counter each time it blocks a stop, and every verdict you commit here is progress, which resets it.
4. Append `review.history` for this round (`{"round": N, "verdict": ..., "critical_high": C, "advisory": A}`); create the array first if the state file predates it.
5. Re-read `.ed3d/orchestrate-state.json` and verify the written `verdict`, `open_critical_high`, `consecutive_blocks: 0`, and new `history` entry before doing anything else.

Only after the state file is committed and verified: print the adversary's full response, then branch on the verdict (step 3).

**A verdict that is not in the state file does not exist.** No stop, no operator report, no dispatch may occur between parsing a verdict and committing it to the state file — one turn, both actions. The guardrail reads the file, not your intentions.

If the response contains no parseable verdict block, treat it as a protocol failure: re-dispatch once with an instruction to end with the verdict block exactly as specified. The protocol failure commits too — leave `verdict: "PENDING"` unchanged, reset `consecutive_blocks: 0`, and append a history entry of exactly `{"round": N, "verdict": "PENDING", "critical_high": 0, "advisory": 0, "note": "adversary protocol failure"}`, so the reset is still progress-tracked. If it fails again, treat as FIX-FIRST with a high finding ("adversary protocol failure") and surface to the operator.

### 3. Branch on the Verdict

**`VERDICT: SHIP`** (no open critical/high):
- Set `review.active: false` in the same state write as (or immediately after) step 2's commit, keeping `verdict: "SHIP"` as the final state. Do not append a second `history` entry for this round — step 2 already appended it. Re-read the state file and verify the terminal state (`active: false`, `verdict: "SHIP"`, `consecutive_blocks: 0`) before reporting — the guardrail hook blocks stops on an inconsistent final SHIP.
- Then report the round count (authoritative source: `review.history`) and any advisory (medium/low) findings left unfixed. Done.

**`VERDICT: FIX-FIRST` with critical/high open:**

- If `round < max_rounds`:
  1. Dispatch `task-bug-fixer` (ed3d-plan-and-execute) without model or effort overrides, leaving model selection to the account's Auto/default; account/CLI defaults decide both. Pass the open critical/high findings verbatim. **Print its full response.**
  2. Verify the fixes are committed and the working tree is clean, then refresh `head_sha` in the state file to the new full 40-character `git rev-parse HEAD`. Every round reviews `BASE_SHA..HEAD` including all fix commits — a stale `head_sha` makes the next round review the pre-fix diff and re-report everything.
  3. Set `round` to `round + 1` and `verdict` to `"PENDING"` in the same state-file write — PENDING marks the adversary back in flight and re-arms the write-guard for the re-review.
  4. Re-dispatch the adversary with the refreshed `HEAD_SHA` and `PRIOR_ISSUES` set to the previous round's open findings.
  5. **Silence is not fixed.** In the new review, any prior issue the adversary does not explicitly confirm fixed with evidence stays on the open list. Carry it forward.
  6. Go to step 2.

- If `round >= max_rounds`: **circuit-break.**
  1. Set `round` to `max_rounds + 1` in the state file (this tells the guardrail hook the cap is reached — it will allow the session to stop and prompt you to surface the decision).
  2. Stop fixing. Present the open critical/high findings to the operator with the round history and ask how to proceed: accept the findings as-is, raise `max_rounds`, or hand off.
  3. When the operator decides: on accept-or-resolved, set `review.active: false`, `verdict: "SHIP"` (operator-accepted), and `consecutive_blocks: 0` before finishing.

**`VERDICT: FIX-FIRST` with an empty critical/high list** (a contract violation by the adversary — FIX-FIRST is defined to mean open critical/high):
- Trust the findings list over the verdict marker. Treat the review as advisory-only (medium/low): fix as appropriate (often worth one quick pass), then set `review.active: false`, `verdict: "SHIP"`, and `consecutive_blocks: 0`, and list what was left unfixed in the final report. Note the protocol deviation in the report.
- This is the deliberate divergence from ed3d-plan-and-execute's zero-Minor policy: in this loop, only critical/high block shipping.

### 4. Rate Limits

If the adversary or bug-fixer dispatch fails with a provider rate-limit error, wait, retry once, and if it persists, serialize all further dispatches (no parallel dispatches for the rest of the loop).

## Review Policy Summary

| Severity | Blocks? | Action |
|----------|---------|--------|
| critical | Yes | Must fix before SHIP |
| high | Yes | Must fix before SHIP |
| medium | No | Fix as appropriate; report what's left |
| low | No | Advisory only |

Max rounds: 3 by default (`review.max_rounds` in the state file), then operator circuit-breaker.
