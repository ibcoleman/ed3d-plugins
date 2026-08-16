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
- You know `BASE_SHA` (before the work) and `HEAD_SHA` (after).
- `.ed3d/orchestrate-state.json` exists and `review.active` is `true`. If it doesn't exist, create the review block before starting:

```json
"review": {
  "active": true,
  "round": 1,
  "max_rounds": 3,
  "verdict": "PENDING",
  "open_critical_high": [],
  "consecutive_blocks": 0
}
```

`max_rounds` defaults to 3; the operator can change it in the state file at any time.

## The Loop

### 1. Dispatch the Adversary

Copilot's subagent dispatch accepts per-dispatch `model` and `reasoning_effort` parameters, and they take precedence over agent frontmatter and `/subagents` defaults. **Always pin them.**

Dispatch `adversary` (ed3d-orchestrate) with `model: kimi-k3`, `reasoning_effort: high`, and:

```
WHAT_WAS_IMPLEMENTED: [summary of the work]
PLAN_OR_REQUIREMENTS: [absolute path to the plan document]
BASE_SHA: [sha]
HEAD_SHA: [sha]
[Round 2+:]
PRIOR_ISSUES:
[verbatim list of open findings from the previous round]
```

**Print the adversary's full response** before doing anything with it.

### 2. Parse the Verdict

From the response, extract:

- `VERDICT: SHIP` or `VERDICT: FIX-FIRST`
- `has_critical_or_high: true|false`
- The findings list

If the response contains no parseable verdict block, treat it as a protocol failure: re-dispatch once with an instruction to end with the verdict block exactly as specified. If it fails again, treat as FIX-FIRST with a high finding ("adversary protocol failure") and surface to the operator.

Update the state file: `verdict`, `open_critical_high` (the list of open critical/high finding one-liners), and `consecutive_blocks: 0` — the guardrail hook increments that counter each time it blocks a stop, and every update you make here is progress, which resets it.

### 3. Branch on the Verdict

**`VERDICT: SHIP`** (no open critical/high):
- Set `review.active: false`, keep `verdict: "SHIP"` as the final state.
- Report the round count and any advisory (medium/low) findings left unfixed. Done.

**`VERDICT: FIX-FIRST` with critical/high open:**

- If `round < max_rounds`:
  1. Dispatch `task-bug-fixer` (ed3d-plan-and-execute) with `model: gpt-5.6-luna`, `reasoning_effort: medium` (use `gemini-3.5-flash` if luna is rate-limited), passing the open critical/high findings, verbatim. **Print its full response.**
  2. Set `round` to `round + 1` in the state file.
  3. Re-dispatch the adversary with `PRIOR_ISSUES` set to the previous round's open findings.
  4. **Silence is not fixed.** In the new review, any prior issue the adversary does not explicitly confirm fixed with evidence stays on the open list. Carry it forward.
  5. Go to step 2.

- If `round >= max_rounds`: **circuit-break.**
  1. Set `round` to `max_rounds + 1` in the state file (this tells the guardrail hook the cap is reached — it will allow the session to stop and prompt you to surface the decision).
  2. Stop fixing. Present the open critical/high findings to the operator with the round history and ask how to proceed: accept the findings as-is, raise `max_rounds`, or hand off.
  3. When the operator decides: on accept-or-resolved, set `review.active: false` and `verdict: "SHIP"` (operator-accepted) before finishing.

**`VERDICT: FIX-FIRST` with an empty critical/high list** (a contract violation by the adversary — FIX-FIRST is defined to mean open critical/high):
- Trust the findings list over the verdict marker. Treat the review as advisory-only (medium/low): fix as appropriate (often worth one quick pass), then set `review.active: false`, `verdict: "SHIP"`, and list what was left unfixed in the final report. Note the protocol deviation in the report.
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
