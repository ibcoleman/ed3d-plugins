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
  "nonce": "a1b2c3d4",
  "provenance": null,
  "recovery": {
    "status": "none",
    "attempts": 0,
    "marker": null
  }
},
"ownership": {
  "status": "unowned",
  "session_id": null,
  "transfer_from": null
}
```

Whenever a review arms — including re-arming an existing inactive review block for a new loop — generate a fresh nonce: 8 lowercase hex characters, written as `review.nonce`, overwriting any prior value. Include it in every adversary dispatch as `NONCE: <value>` — the guardrail hook matches rendered verdicts by this tag, which is what keeps the literal `VERDICT: SHIP` strings in skill and agent prose from being mistaken for a real verdict (that false match fabricated a terminal SHIP live on 2026-08-16). Never reuse a nonce across loops.

- **Resume reconciliation.** If resuming into an active review (`review.active: true` on resume), reconcile first: any verdict already rendered in this session's transcript but absent from the state file must be written to the state file before any new dispatch. Do not dispatch a fresh adversary to "check" a verdict the transcript already contains. (This recovers same-session omissions only — after `/clear` the transcript is gone, the state file is the sole truth, and a stale `PENDING` on an already-completed loop can then only be caught by the operator or the round history.)

### Owner, provenance, and bounded reconciliation

The state contract always carries `"ownership"` with statuses `unowned`,
`owned`, `transfer_pending`, or `recovery_required`; it carries
the `"provenance"` field (`review.provenance`) as `null` before dispatch and then the current `round`,
`dispatch_tool_call_id`, and `reviewer_agent_id`. The command's three explicit
resume paths are **same-owner continuation**, **authorized ownership transfer**,
and **explicit legacy recovery**. A transfer requires the old owner to write
`transfer_pending` before `/clear`; an unrelated session cannot inherit it.
Missing identity uses `ownership-recovery-required` without mutating state.

### Executable owner and provenance checklist

At review arm, read the live session identity (the parent session identity)
and persist
`ownership.status: owned` with the current task, absolute plan, phase, and
exact `session_id`; re-read it before dispatch. If the session identity is unavailable,
leave ownership unbound (or normalize malformed legacy state to
`recovery_required`), do not dispatch or infer a verdict, and surface
`ownership-recovery-required`.

For a new review round (initial arm or FIX-FIRST advance), clear `review.provenance`,
set the current `review.round`/`review.verdict` to the new
`PENDING` review, and reset the recovery block to `status: none`,
`attempts: 0`, `marker: null` before the first dispatch. After either
supported parent dispatch observation, persist `review.provenance` with the
current `round` and `dispatch_tool_call_id`. After `subagent.started`, persist
`reviewer_agent_id`; re-read the state and require the round, dispatch ID, and
reviewer ID to agree before parsing the completion.

Same-round reconciliation/protocol retry is a separate state-machine
transition. Before the sole retry dispatch, persist
`review.recovery.status: reconciliation_retrying`, `attempts: 1`, and marker
`review-reconciliation-unavailable`. Preserve that state, the round, nonce,
history, SHAs, approval, and ownership through dispatch, continuation, and
authorized transfer; never reset it as retry initialization. Do not preserve
failed dispatch/reviewer provenance: clear only `review.provenance` before
the retry, then replace it with the new observed dispatch tool-call ID and
reviewer agent ID from that retry's parent dispatch/start pair. If the retry
is unavailable again, atomically write
`reconciliation_exhausted`, attempts `1`, inactive/PENDING/no-verdict state.
Only a new round or an explicitly authorized same-owner resume from exhausted
may reset `status: none`, `attempts: 0`, `marker: null` and grant one fresh
retry budget. Missing, malformed, or cross-round provenance keeps the owner
blocked with `review-reconciliation-unavailable` and never fabricates a
verdict.

When a different context will resume, the current owner must, before `/clear`,
write and re-read `ownership.status: transfer_pending` with
`transfer_from` equal to its live `session_id`, preserving task/plan/phase,
approval, active review, round, nonce, and history. `/clear` is only a context
handoff, not approval or an ownership claim. Same-owner continuation keeps
`owned`; the fresh context must use explicit `resume` to claim a pending
transfer before it continues.

Reconciliation is a conservative streaming JSONL scan, not substring matching.
The dispatch `toolCallId`, `subagent.started`, expected reviewer
`assistant.message`, and `subagent.completed` must form one current lineage.
`tool.execution_complete` result content is never verdict evidence. The latest
reviewer message must end with exactly two lines:
`VERDICT: SHIP [<nonce>]` plus `has_critical_or_high: false`, or
`VERDICT: FIX-FIRST [<nonce>]` plus `has_critical_or_high: true`. Quoted,
fenced, duplicate, trailing, stale, wrong-lineage, and out-of-order variants
are unavailable. The parser retains bounded state and scans past 256 KiB.

Missing reviewer completion provenance with an active PENDING review remains
ordinary owner enforcement. When a bound completed-result check is unavailable,
persist the retrying marker before using the existing one current-round
protocol retry, not repeated stop blocking. On the
second unavailable result, write `reconciliation_exhausted`, attempts `1`,
`review.active: false`, and `review.verdict: "PENDING"` atomically. no verdict
exists; the phrase "no verdict exists" is the required operator diagnostic;
stopping is allowed only with the diagnostic marker and an explicit
operator choice to re-arm or abandon. A later same-owner resume may reset the
recovery block and re-arm one attempt, but never fabricates SHIP.

Protocol failure uses this same state transition. Record exactly one
same-round `protocol failure`/`PENDING` history entry, persist the retrying
marker, and allow exactly one protocol re-dispatch. If the retry again has no parseable verdict, persist the
complete exhausted no-verdict state (`reconciliation_exhausted`,
`review.active: false`, `review.verdict: "PENDING"`, `attempts: 1`, and the
diagnostic marker), report that no verdict exists, and require an explicit
operator choice to re-arm or abandon. This path must never SHIP.

`max_rounds` defaults to 3; the operator can change it in the state file at any time.

`review.history` is the append-only round record (create the array if the state file predates it — in-flight 0.2.x state files do):

```json
"history": [
  {"round": 1, "verdict": "FIX-FIRST", "critical_high": 1, "advisory": 6},
  {"round": 2, "verdict": "SHIP", "critical_high": 0, "advisory": 0}
]
```

`critical_high` / `advisory` are the counts of findings at those severities in that round's report. Entries are append-only — never rewrite prior entries. An optional `note` string is the entry schema's only sanctioned extension point; no other keys. Rounds legitimately split across `/clear`+resume session boundaries, so per-session dispatch counts undercount the loop; `history` is the authoritative round count for the final report. The round count is the highest `round` value in `history`, not its length — a round can legitimately hold more than one entry (a protocol-failure `PENDING` followed by that round's actual verdict).

### State transition checklist

Before dispatching, branching, or stopping, verify the state-file transition
against the committed evidence:

- **fresh task:** the canonical state has pending approval, a `not_started`
  handoff, zero correction attempts, empty history, and a null nonce;
- **plan binding:** the plan path is absolute and exists, the baseline is
  valid, the phase is `execute`, and approval remains pending until the later
  explicit authorization;
- **approval:** the current task and plan match, then approval is granted
  immediately before the first builder dispatch;
- **review arm:** `base_sha` and `head_sha` are distinct valid commits, the
  outcome handoff is verified, review is active/PENDING at round 1, and the
  nonce is fresh;
- **verdict:** persist and re-read `verdict`, open findings,
  `consecutive_blocks: 0`, and the new history entry before printing or
  branching;
- **FIX-FIRST:** verify the fixer commit, refresh `head_sha`, advance the
  round, set PENDING, and preserve prior findings before re-review;
- **terminal SHIP:** active is false, verdict is SHIP, consecutive blocks is
  zero, and the highest history round carries the final verdict.

History is append-only: write one terminal verdict entry per review round.
The only same-round exception is at most one same-round `PENDING` entry carrying exactly
the note `"adversary protocol failure"` before that round's terminal entry.
The round count is the highest round value, not the history length. A verdict
not written and re-read from the state file does not exist. The hook retains
atomic temporary-file replacement. It does not protect concurrent model-mediated state edits;
those writes remain procedural.

## The Loop

### 1. Dispatch the Adversary

<!-- DISPATCH-PROTOCOL:BEGIN -->
#### Bounded pinned-first dispatch protocol

The `adversary` dispatch uses preferred model `gpt-6-astra` and effort `medium` on its first attempt, expressed as `model="gpt-6-astra"` and `reasoning_effort="medium"` overrides. Invoke the named resource through Copilot's native agent/subagent delegation mechanism; do not call the Skill loader for agent names. Preserve the exact review prompt, plan path, `BASE_SHA`, `HEAD_SHA`, `NONCE`, prior issues, role, and working directory.

A fallback is permitted exactly once, and only when an explicit pre-start rejection identifies model availability, account availability, or effort support. Fallback rule: make exactly one Auto fallback with both `model` and `reasoning_effort` overrides omitted; preserve every other dispatch input. A fallback rejection is terminal.

Classify a rate-limit error separately: use the existing wait, retry-once, then serialize/small-batch behavior; it does not consume the model fallback or change the selected model/effort policy. A started/no-verdict dispatch follows the existing protocol-failure path and may take at most its existing one protocol re-dispatch, preserving the current selection mode; never switch to the fallback after a start signal; protocol-failure proceeds without model fallback. An ambiguous refusal or no-start outcome is terminal and must not be retried.

The dispatch lineage allows at most three semantic submissions: preferred, the sole Auto fallback, and one separately named protocol-failure re-dispatch. never issues the fallback twice, never combines protocol retry with model fallback, or duplicates an ambiguous outcome. Report preferred success, explicit rejection plus fallback retry, fallback result, protocol failure, or ambiguous refusal prominently, and print the full response after every attempt before taking the next action.

Site requirement: the primary `adversary` dispatch is pinned-first with `gpt-6-astra` / `medium`, then one Auto fallback omitting both overrides only after explicit pre-start model/account/effort rejection, preserving the exact review prompt, plan path, SHAs, nonce, prior issues, role, and working directory. Rate-limit and protocol-failure handling remain separate.

For the FIX-FIRST branch, dispatch `task-bug-fixer` with preferred model `gpt-5.6-luna` and effort `high`, expressed as `model="gpt-5.6-luna"` and `reasoning_effort="high"` overrides. Its one Auto fallback omits both overrides only after the same explicit pre-start rejection, preserving the exact fixer prompt, findings, role, path, and working directory. Rate-limit and protocol-failure handling remain separate.

<!-- DISPATCH-PROTOCOL:END -->

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

If the response contains no parseable verdict block, treat it as a protocol
failure: re-dispatch exactly once with an instruction to end with the verdict
block exactly as specified. The protocol failure commits too — leave
`verdict: "PENDING"` unchanged, reset `consecutive_blocks: 0`, and append a
history entry of exactly
`{"round": N, "verdict": "PENDING", "critical_high": 0, "advisory": 0, "note": "adversary protocol failure"}`
so the reset is progress-tracked. If the one retry also fails, do not turn the
absence of a verdict into FIX-FIRST or SHIP: persist the complete
`reconciliation_exhausted`/inactive/PENDING state with `attempts: 1` and the
diagnostic marker, report that no verdict exists, and require an explicit
operator choice to re-arm or abandon.

### 3. Branch on the Verdict

**`VERDICT: SHIP`** (no open critical/high):
- Set `review.active: false` in the same state write as (or immediately after) step 2's commit, keeping `verdict: "SHIP"` as the final state. Do not append a second `history` entry for this round — step 2 already appended it. Re-read the state file and verify the terminal state (`active: false`, `verdict: "SHIP"`, `consecutive_blocks: 0`) before reporting — the guardrail hook blocks stops on an inconsistent final SHIP.
- Then report the round count (authoritative source: `review.history`) and any advisory (medium/low) findings left unfixed. Done.

**`VERDICT: FIX-FIRST` with critical/high open:**

- If `round < max_rounds`:
  1. Invoke the named resource through Copilot's native agent/subagent delegation mechanism; do not call the Skill loader for agent names. Dispatch `task-bug-fixer` (ed3d-plan-and-execute) according to the bounded pinned-first protocol above, preserving the open critical/high findings verbatim. **Print its full response.**
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

### 5. Final reporting and exhausted recovery

The normal final report is permitted only after a committed SHIP state has
been re-read and verified (`review.active: false`, `review.verdict: "SHIP"`,
and `consecutive_blocks: 0`). An exhausted reconciliation or second protocol
failure is not a terminal SHIP outcome: verify
`review.active: false`, `review.verdict: "PENDING"`,
`review.recovery.status: "reconciliation_exhausted"`,
`review.recovery.attempts: 1`, and
`review.recovery.marker: "review-reconciliation-unavailable"`; report the
failure and that no verdict exists. Stop only with the diagnostic marker and
an explicit operator choice to re-arm or abandon. Re-arm is an authorized
same-owner `resume` followed by exactly one fresh retry; abandon preserves the
inactive/PENDING no-verdict state. Never write or report SHIP for exhaustion.

## Review Policy Summary

| Severity | Blocks? | Action |
|----------|---------|--------|
| critical | Yes | Must fix before SHIP |
| high | Yes | Must fix before SHIP |
| medium | No | Fix as appropriate; report what's left |
| low | No | Advisory only |

Max rounds: 3 by default (`review.max_rounds` in the state file), then operator circuit-breaker.
