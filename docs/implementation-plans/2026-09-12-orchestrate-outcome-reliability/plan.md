# Goal

Improve `ed3d-orchestrate` delivery reliability without building a new
orchestration framework. A new task must not inherit an old task's approval or
resume position; a builder must demonstrate the requested outcomes rather than
only report a green existing suite; and state/verdict transitions must remain
explicit and recoverable. Preserve the independent adversary, the existing
bounded fixer loop, read-only planning restrictions, and Branch B's
protocol-only approval boundary.

This plan deliberately does not claim universal runtime enforcement. The
repository has no validated native builder-dispatch payload and agent identity,
so static assertions and bounded synthetic replays establish document/protocol
contracts and instruction-following evidence, not an unbypassable builder gate.

# Implementation Summary

1. Make a non-empty task invocation start a fresh loop, while an empty
   invocation resumes only a validated in-progress state. Reset all existing
   task, plan, approval, SHA, and review fields to known defaults. If planning
   mode is read-only, record a simple pending-reset handoff in the plan
   artifact and refuse execution until the reset is applied after planning.
2. Add a concise outcome-specific builder/fixer handoff. Each approved
   acceptance criterion is listed with a `complete`, `incomplete`, or `blocked`
   status, changed location, and behavior-specific command/result. The
   orchestrator checks the handoff before arming review. One missing-outcome
   correction is allowed through the existing fixer; a second incomplete
   handoff becomes an explicit blocker/replan decision.
3. Clarify state transition and verdict-recording checklists in the existing
   skills and strengthen their contract/replay tests. Keep the existing hook's
   atomic temporary-file replacement and terminal-state checks, but do not claim
   that a hook-only write protects concurrent model-mediated state edits.

The only state addition is a small `handoff` block used to make the bounded
correction visible:

```json
"handoff": {
  "status": "not_started",
  "correction_attempts": 0,
  "remaining_outcomes": []
}
```

The canonical fresh state otherwise uses the existing structure:

```json
{
  "task": "one-line task",
  "plan_path": null,
  "base_sha": null,
  "head_sha": null,
  "phase": "research",
  "gate": {"approval": "pending"},
  "handoff": {
    "status": "not_started",
    "correction_attempts": 0,
    "remaining_outcomes": []
  },
  "review": {
    "active": false,
    "round": 0,
    "max_rounds": 3,
    "verdict": "PENDING",
    "open_critical_high": [],
    "consecutive_blocks": 0,
    "history": [],
    "nonce": null
  }
}
```

A review nonce remains `null` until review arms, then is generated fresh for
that loop as the existing protocol requires. `max_rounds` resets to `3` on a
new task. Existing plans, commits, and other repository work remain untouched;
only the current control-plane state is reset.

# Implementation Plan

## 1. Fresh-task reset and approval handoff

Target files:

- `plugins/ed3d-orchestrate/README.md`
- `plugins/ed3d-orchestrate/commands/orchestrate.md`
- `plugins/ed3d-orchestrate/skills/orchestrating-the-loop/SKILL.md`
- `scripts/test_context_handoff_protocol.py`
- `scripts/test_context_handoff_documentation.py`
- `scripts/test_orchestrate_event_replay.py`
- `scripts/fixtures/orchestrate-events/`

Changes:

- A non-empty task argument always wins over auto-resume and resets the
  canonical fresh state above. Reset `task`, `plan_path`, `base_sha`,
  `head_sha`, `phase`, `gate.approval`, `handoff`, all review fields, and
  counters together. A prior `"granted"` value, plan path, SHA, nonce, history,
  or correction attempt cannot survive into the new task.
- An empty invocation may resume only when the state is valid JSON, has
  `phase: "execute"` or `"review"`, has a non-empty absolute `plan_path` that
  exists, and has a task that matches the plan context. The clean fresh
  combination `review.active: false` and `review.verdict: "PENDING"` is not
  automatically treated as an in-progress loop. Malformed, partial, legacy,
  or mismatched state fails closed and returns to the pending fresh baseline.
- Preserve the current approval boundary: the plan-review turn writes
  `phase: "execute"` and `gate.approval: "pending"`; a later explicit
  `continue` or `/clear` plus resume writes `"granted"` immediately before
  the first builder dispatch. The task and absolute plan path are checked
  against the current state before that write. The current turn/immediacy rule
  is protocol-only and is represented by the existing synthetic replay seam;
  no native dispatch enforcement is claimed.
- When read-only plan mode prevents the reset write, the plan artifact records
  this permitted handoff section:

  ```markdown
  ## Orchestration Handoff
  - reset_pending: true
  - requested_task: <task text>
  - prior_task: <task text or unknown>
  - prior_plan_path: <absolute path or none>
  - approval: pending
  ```

  It is an explicit pending record, not authorization. On leaving plan mode,
  the orchestrator applies the reset, verifies the state task and plan path,
  and changes `reset_pending` to `false` in its control-plane handling before
  approval. If the record is missing, duplicated, or does not match the
  requested task, execution remains refused. Phase 2 still writes only the
  plan document.
- Extend the existing replay seam and fixtures with a stale-grant/new-task
  case, a clean-default-no-auto-resume case, and a pending-reset case. Keep
  the replay documentation explicit that these are synthetic protocol tests.

## 2. Outcome-specific builder handoff and bounded recovery

Target files:

- `plugins/ed3d-plan-and-execute/agents/task-implementor-fast.agent.md`
- `plugins/ed3d-plan-and-execute/agents/task-bug-fixer.agent.md`
- `plugins/ed3d-orchestrate/skills/orchestrating-the-loop/SKILL.md`
- `plugins/ed3d-orchestrate/agents/adversary.agent.md`
- `scripts/test_orchestrate_agent_dependencies.py`
- `scripts/test_context_handoff_protocol.py`

Changes:

- Add a Copilot-native handoff section to builder and fixer reports:

  ```markdown
  ### Outcome Handoff
  - AC.1: complete | incomplete | blocked
    - Changed: file or symbol
    - Evidence: command -> observed result
  ```

  Require one concise row for every approved `AC.n` or explicitly requested
  behavior. `incomplete` and `blocked` rows include the remaining gap. A green
  pre-existing suite without behavior-specific evidence is not completion.
- Keep the frozen Claude agent bodies unchanged. Update only the Copilot
  `*.agent.md` resources and adjust the existing twin test to permit this
  documented Copilot-only handoff section while retaining all other role-body
  parity checks.
- Before recording `head_sha` or arming adversarial review, the orchestrator
  compares the report rows with the approved plan criteria. This is a
  procedural handoff check backed by static contract tests and bounded agent
  responses, not a universal semantic parser.
- On the first missing/incomplete requested outcome, set
  `handoff.status: "pending"`, increment `correction_attempts` to `1`, and
  dispatch the existing `task-bug-fixer` once with only the missing outcomes
  and their evidence gaps. Do not arm adversarial review while the handoff is
  pending.
- If the fixer refuses, fails to commit, or returns another incomplete/blocked
  handoff, set `handoff.status: "blocked"` and retain
  `remaining_outcomes`. Keep `review.active: false` and
  `gate.approval: "pending"`; report a concrete takeover/replan decision.
  Resume must not silently dispatch a second fixer. A new task reset clears
  the block; an explicit operator takeover may continue with the preserved
  commit, but remains subject to independent review.
- The adversary still reviews the complete committed range independently and
  remains the authority for SHIP/FIX-FIRST findings after the handoff is
  verified. Missing implementation is routed to execution correction, not
  disguised as a review finding.

## 3. State transitions and verdict recording

Target files:

- `plugins/ed3d-orchestrate/skills/adversarial-review/SKILL.md`
- `plugins/ed3d-orchestrate/skills/orchestrating-the-loop/SKILL.md`
- `plugins/ed3d-orchestrate/hooks/check-review-loop.py`
- `plugins/ed3d-orchestrate/hooks/test-check-review-loop.py`
- `scripts/test_context_handoff_protocol.py`
- `scripts/test_context_handoff_documentation.py`

Changes:

- Add a transition checklist using the existing fields:
  - fresh task: canonical state above;
  - plan binding: absolute existing `plan_path`, `phase: execute`, valid
    baseline, pending approval;
  - approval: explicit later authorization, matching current task/plan, then
    granted immediately before dispatch;
  - review arm: committed distinct `base_sha`/`head_sha`, verified handoff,
    active/PENDING review, round 1, fresh nonce;
  - verdict: persist and re-read `verdict`, open findings,
    `consecutive_blocks: 0`, and history before printing or branching;
  - FIX-FIRST: verify the fixer commit, refresh `head_sha`, advance the round,
    set PENDING, and preserve prior findings before re-review;
  - terminal SHIP: active false, SHIP, zero consecutive blocks, and the
    highest history round matches the final verdict.
- State explicitly that a verdict not written and re-read from the state file
  does not exist. History remains append-only: one terminal verdict entry per
  review round, with at most one same-round `PENDING` entry carrying the
  existing exact `"adversary protocol failure"` note before a terminal entry.
  The round count remains the highest round value, not the history length.
- Retain the existing `check-review-loop.py` temporary-file plus `os.replace`
  update and its fail-open behavior for malformed state. Do not add a
  hook-only concurrency guarantee: the orchestrator's model-mediated writes
  remain procedural, and the plan must state that limitation plainly.
- Add focused static assertions for reset defaults, pending handoff,
  outcome-before-review ordering, verdict persistence/re-read, history
  semantics, counter reset, and terminal SHIP. Extend the existing replay
  fixtures only for approval/reset ordering; do not invent a new state-machine
  test framework or a new builder hook.
- Keep `hooks.json` and the Branch B no-builder-gate contract unchanged.

# Acceptance Criteria

1. **AC.1 New-task reset is explicit and complete.** A task-bearing invocation
   resets every field in the canonical fresh state, including approval,
   `handoff`, `review.max_rounds`, history, counters, and nonce. Existing
   plans/commits remain untouched. Verified by the reset/default assertions in
   `scripts/test_orchestrate_event_replay.py` and
   `scripts/test_context_handoff_protocol.py`.
2. **AC.2 Resume and approval handoff are stale-safe at the protocol seam.**
   A clean default, malformed state, legacy state, mismatched task/plan,
   pending reset, bare resume, or prior task's grant cannot authorize a replayed
   builder. Pending is recorded before a later explicit grant and dispatch.
   Verified by `python3 scripts/test_orchestrate_event_replay.py`,
   `python3 scripts/test_context_handoff_protocol.py`, and
   `python3 scripts/test_context_handoff_documentation.py`. These tests do not
   claim native mechanical enforcement.
3. **AC.3 Read-only planning is preserved.** Phase 2 writes only `plan.md`;
   when reset must wait, the plan contains the simple pending handoff record
   and execution remains refused until it is applied. Verified by
   `python3 scripts/test_plan_artifact_contract.py` and the read-only/reset
   assertions in `scripts/test_context_handoff_documentation.py`.
4. **AC.4 Builder completion is outcome-specific.** Builder and fixer reports
   require a concise row for every approved outcome with status, changed
   location, and behavior-specific command/result; a suite-only claim is
   insufficient. Verified by
   `python3 scripts/test_orchestrate_agent_dependencies.py` and the
   handoff-order assertions in `scripts/test_context_handoff_protocol.py`.
5. **AC.5 Missing outcomes receive one bounded recovery attempt.** The first
   incomplete handoff routes only the gap to the existing fixer before review;
   refusal, missing commit, or a second incomplete handoff records a blocked
   state with remaining outcomes and requires an explicit takeover/replan
   decision. Verified by the Phase 4 handoff assertions in
   `scripts/test_context_handoff_protocol.py` and
   `scripts/test_context_handoff_documentation.py`.
6. **AC.6 Independent review remains unchanged.** The adversary still receives
   the full `BASE_SHA..HEAD_SHA`, nonce, and prior findings, cannot write during
   PENDING review, and only critical/high findings route through the existing
   fixer path. Verified by
   `python3 plugins/ed3d-orchestrate/hooks/test-adversary-write-guard.py`,
   `python3 plugins/ed3d-orchestrate/hooks/test-check-review-loop.py`,
   `python3 scripts/test_orchestrate_agent_dependencies.py`, and
   `python3 scripts/test_orchestrate_enforcement_branch.py`.
7. **AC.7 Verdict recording is explicit and recoverable.** Every verdict is
   persisted and re-read before reporting; history is append-only with the
   documented protocol-failure exception; progress resets
   `consecutive_blocks`; terminal SHIP fields are consistent; malformed state
   never becomes a fabricated verdict. Verified by
   `python3 plugins/ed3d-orchestrate/hooks/test-check-review-loop.py`,
   `python3 scripts/test_context_handoff_protocol.py`, and
   `python3 scripts/test_orchestrate_event_replay.py`.
8. **AC.8 Copilot package contracts remain intact.** The frozen Claude agent
   files are unchanged, Copilot agent files contain the outcome handoff,
   Branch B has no builder-gate artifact or registration, and README/skill
   state documentation agrees. Verified by
   `python3 scripts/test_orchestrate_agent_dependencies.py`,
   `python3 scripts/test_orchestrate_enforcement_branch.py`, and
   `python3 scripts/validate_plugins.py`.

# Test Strategy

- Extend the existing stdlib-only replay fixtures for stale grants after a
  task reset, clean-default no-auto-resume, and pending-reset refusal. Keep
  the replay README text explicit that the seam is synthetic and protocol-only.
- Extend the existing context-handoff/documentation tests with source-order
  assertions for reset-before-approval, outcome-before-review, one correction
  attempt, blocked handoff, and no native builder-gate claims.
- Extend the existing agent-dependency test to require the Copilot-only
  `Outcome Handoff` section in both `.agent.md` resources while preserving the
  frozen-source parity checks for all other content. Add static assertions over
  the adversary prompt for range, nonce, prior findings, and no-write behavior.
- Run the two existing hook suites for counter updates, malformed-state
  behavior, nonce matching, write blocking, and terminal SHIP checks. Do not
  add a concurrency claim or test that the available writer boundary cannot
  support.
- Run the targeted command batch after implementation:
  `python3 scripts/test_orchestrate_event_replay.py`,
  `python3 scripts/test_context_handoff_protocol.py`,
  `python3 scripts/test_context_handoff_documentation.py`,
  `python3 scripts/test_orchestrate_agent_dependencies.py`,
  `python3 scripts/test_plan_artifact_contract.py`,
  `python3 scripts/test_orchestrate_enforcement_branch.py`,
  `python3 plugins/ed3d-orchestrate/hooks/test-check-review-loop.py`,
  `python3 plugins/ed3d-orchestrate/hooks/test-adversary-write-guard.py`, and
  `python3 scripts/validate_plugins.py`.

### Maintained verification gate and baseline exclusions

For this plan, the maintained verification gate is the targeted command batch
above plus the package validator. It intentionally does **not** include the
legacy `scripts/test-dispatch-protocol.py` release-needle check or the
historical portability-audit fixture suite
(`scripts/test_validate_portability_audit.py`): the former still asserts the
pre-existing 0.4.1 release while the checked-in package is 0.5.0, and the
latter references a historical plan path that is not present in this checkout.
Those commands remain known red baseline checks and are reported separately;
they are not evidence of a regression in this plan and are not silently
removed or weakened. Updating either legacy contract requires a separate
version/fixture-maintenance change outside this plan's scope.

# Review Strategy

Use one coherent Copilot builder task because reset, handoff, and state
documentation share the same vocabulary. Before arming review, inspect the
builder's outcome handoff against the plan and allow at most one directed
completion correction through `task-bug-fixer`. A blocked handoff stops with a
resumable operator decision rather than entering the dryer. Once verified, use
the independent adversary over the complete commit range and preserve the
existing critical/high-only fixer routing and three-round cap.

# Risks

- **Approval and outcome checks are procedural.** Static contracts and bounded
  synthetic replays provide evidence that the orchestrator instructions are
  explicit and correctly ordered; they do not mechanically intercept every
  native builder dispatch or semantically prove a claimed test result.
- **Read-only plan mode can defer reset.** The pending handoff is deliberately
  not authorization. If it cannot be applied after planning mode, the loop
  remains blocked with a concrete task/plan record instead of running stale
  work.
- **No shared-writer concurrency guarantee.** The existing stop hook's atomic
  replacement remains covered, but model-mediated state writes are outside its
  lock boundary. The implementation must not claim that hook behavior prevents
  races between arbitrary writers.
- **Outcome handoff can be incomplete despite honest reporting.** The
  behavior-specific evidence requirement improves detection, while independent
  adversarial review remains necessary for correctness and regressions.
- **Scope exclusions.** Model tuning, dashboards or telemetry, a new
  orchestration framework, broad testing-policy rewrites, release cleanup, and
  unrelated repository fixes are out of scope. Independent review and bounded
  correction are explicitly in scope.
- **Future mechanical enforcement.** Reconsidering Branch B requires a fresh
  captured native builder-dispatch payload and agent identity plus a separate
  reviewed plan; this change does not attempt it.
