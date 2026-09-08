# Polytoken-inspired durable goals for `ed3d-orchestrate`

## Goal

Add a Copilot-native approximation of Polytoken's saved-session goal feature to `ed3d-orchestrate`. An operator must be able to keep one durable, inspectable objective in the existing repository-local `.ed3d/orchestrate-state.json` across `/clear`, explicit resume, plan-review pauses, and terminal completion or blockage, without coupling goal lifecycle to the orchestration phase, adversarial review block, or plan-to-builder approval.

The feature is intentionally an approximation, not Polytoken runtime parity. Official Polytoken documentation defines `/goal`, `/goal set <text>`, `/goal pause`, `/goal resume`, and `/goal clear` as session-goal commands; its model tools include `propose_goal`, `read_goal`, `complete_goal`, and `block_goal` (P1, P2). Polytoken persists session work independently of context clearing and compaction (P3), and its daemon can automatically continue an active goal subject to `max_continuations_per_goal`; `agent_goal_auto_accept` controls approval of model-proposed goals (P4). Copilot plugin surfaces provide no verified equivalent of that daemon-owned continuation driver or native goal-approval overlay. This release therefore provides durable state and explicit command/resume continuation only; it must not claim autonomous Copilot restart, native model-proposal approval, or mechanical builder-gate enforcement.

The feature must preserve the existing plan-review → operator approval → builder workflow. In particular, `goal resume` may reactivate a paused objective but must never write or imply `gate.approval: "granted"`.

## Implementation Summary

1. Add a sibling `goal` block to the existing state schema. Keep `phase`, `gate.approval`, and `review.*` authoritative for their current concerns.
2. Add an explicit `/ed3d-orchestrate:goal` command with `show`, `set`, `set --replace`, `pause`, `resume`, `clear`, `complete`, and `block` operations. Ordinary `set` refuses to replace an active goal; replacement is explicit and auditable.
3. Add a small stdlib-only state-transition module, `scripts/orchestrate_goal_state.py`, so command prose delegates validation, migration, atomic writes, timestamps, goal identity, and transition legality to deterministic code rather than relying only on model compliance.
4. Add deterministic transition and JSONL replay tests covering every legal and illegal transition, legacy-state migration, malformed input, continuation-cap blocking, and the invariant that goal resume leaves `gate.approval` unchanged.
5. Update the orchestrator command/skill/README and release metadata. Extend existing contract/dispatch/scope validation without changing either existing hook registration or hook decision logic.
6. Map existing terminal orchestration outcomes without changing their review semantics: SHIP/operator-accepted completion becomes `completed`; a circuit-break is a nonterminal `active` hold awaiting the existing operator decision; operator rejection/stop and unrecoverable/protocol failure become `blocked` with a durable reason. A paused goal suppresses new dispatch at the next safe orchestration boundary but does not pretend to cancel already-running Copilot work.

### Resolved design decisions

| Decision | Resolution | Rationale / boundary |
|---|---|---|
| Scope | Repository-scoped, one current goal per `.ed3d/orchestrate-state.json` | Reuses the only existing durable substrate. It is not a global or cross-repository store and does not promise Polytoken's session identity semantics. Concurrent Copilot sessions editing one repository remain a documented residual risk. |
| Current schema | `goal: null` or a goal object; object is a sibling of `gate` and `review` | Unknown top-level fields are ignored by current hooks, and the existing state file remains the audit trail. |
| Goal identity | `goal_id`: 16 lowercase hexadecimal characters from a cryptographically strong random source on every new/replaced goal | Distinguishes goal instances in history and prevents a replacement from being mistaken for a resume. Tests inject a deterministic ID source; no identity is used as a Copilot runtime claim. |
| Public statuses | `active`, `paused`, `completed`, `blocked`, `cleared` | `completed`, `blocked`, and `cleared` are terminal for the current identity; a new objective requires explicit replacement. |
| Replacement | `set <text>` creates only when no current goal exists or the current status is `cleared`; `set --replace <text>` is required for an active, paused, completed, or blocked goal | Prevents silent loss of active work. Replacement records a history event and creates a new `goal_id`. |
| Clear/history | `clear` is a retirement transition, not deletion. It preserves the current goal fields and append-only `history`, setting `status: "cleared"`, `last_action: "clear"`, and `block_reason: null`; `clear` on a null goal is a successful no-op with no file write | Recovery and audit remain possible without a second goal database. `show` can explain what was cleared. |
| Pause | Valid only from `active`; records `paused` at the next safe boundary. It does not cancel or interrupt a live builder/reviewer/job | Copilot has no reliable plugin-level cancellation/continuation primitive that this feature can own. |
| Resume | Valid only from `paused`; returns to `active`, increments `continuations`, and leaves `gate.approval` byte-for-byte unchanged | A resumed goal can still encounter `phase: "execute"` with pending approval and must re-present the existing checkpoint. |
| Continuation cap | `max_continuations` defaults to `50`, matching Polytoken's documented `max_continuations_per_goal` default; `continuations` counts explicit goal resumes/re-entry attempts for this goal. A resume at the cap transitions to `blocked` with reason `continuation cap reached` | This is accounting and loop protection, not an autonomous driver. There is no automatic restart after a turn, process exit, or background job. The cap is an approximation because Copilot has no daemon goal driver. |
| Complete | Explicit `complete` is valid only when the state has a terminal review outcome (`review.active: false` and `review.verdict: "SHIP"`, including operator-accepted SHIP). Existing SHIP/report paths also perform the transition when a goal is active | Prevents a goal from claiming completion before the existing review contract is terminal. |
| Block | Explicit `block <reason>` requires a non-empty reason and is valid from `active` or `paused`; operator rejection/stop, unrecoverable state, and protocol-failure paths use the same transition. A circuit-break itself is only an active hold until that operator decision | A blocked goal never silently resumes. A later `set --replace` is the operator action that starts a new objective. |
| Timestamps | RFC 3339 UTC strings with a `Z` suffix; `created_at` is immutable for an identity, `updated_at` changes on every transition | Human-readable and deterministic to validate. Tests inject a clock. |
| History | Append-only transition records in `goal.history`, retaining all goal identities in this repository state file. Each record contains `at`, `action`, `from`, `to`, `goal_id`, and optional `reason` | No deletion of audit evidence. History is not a second database and is not read by existing review hooks. |
| Migration | Missing `goal` means legacy state with no active goal. Read/show is non-mutating and reports legacy/no-goal. The next successful goal mutation adds `goal` in the resulting state; a legacy `show` remains non-mutating. Because no goal mutation can be performed while `goal` is absent except `set`, legacy `set` creates the first goal object directly rather than writing an intermediate `goal: null`. Malformed goal data fails closed for goal operations and is not silently repaired | Existing orchestration fields remain untouched. No migration script or eager rewrite is needed. |
| Hook behavior | Existing hooks remain fail-open and continue to read only `review.*`; no goal hook or builder-gate hook is added | Preserves Branch B protocol-only status and avoids unsupported Copilot payload assumptions. |

### Goal state and transition table

The state object for an active goal is:

```json
{
  "goal": {
    "goal_id": "0123456789abcdef",
    "text": "Implement and validate the goal feature for ed3d-orchestrate",
    "status": "active",
    "continuations": 0,
    "max_continuations": 50,
    "created_at": "2026-09-07T00:00:00Z",
    "updated_at": "2026-09-07T00:00:00Z",
    "last_action": "set",
    "block_reason": null,
    "history": [
      {
        "at": "2026-09-07T00:00:00Z",
        "action": "set",
        "from": null,
        "to": "active",
        "goal_id": "0123456789abcdef"
      }
    ]
  }
}
```

`goal` may be `null` in a fresh or migrated legacy state. The transition engine must implement this table:

| Current | Action | Required precondition | Next state | Invalid behavior |
|---|---|---|---|---|
| `null` | `show` | None | Report no active goal; no state mutation | Read-only success |
| `null` | `set` | Non-empty text | `active`, new ID, counters reset | Reject empty text; no write |
| `null` | `pause` / `resume` / `complete` / `block` | None | None | Reject with no write; `block` still requires a reason before source validation |
| `cleared` | `set` | Non-empty text | `active`, new ID, history retained | Reject empty text; no write |
| `active` / `paused` / `completed` / `blocked` | `set` | `--replace`, non-empty text | `active`, new ID, history appended, counters reset | Without `--replace`, reject and preserve state |
| `active` | `pause` | None | `paused` | Reject from other statuses |
| `paused` | `resume` | `continuations < max_continuations` | `active`, counter +1 | At cap: `blocked`; otherwise reject non-paused |
| `null` | `clear` | None | `null`, no write | Successful no-op; report that no goal exists |
| `active` / `paused` / `completed` / `blocked` / `cleared` | `clear` | None | `cleared`, same ID | Idempotent clear is a successful no-op when already `cleared`: it does not append history or change timestamps |
| `active` | `complete` | `review.active == false` and `review.verdict == "SHIP"` | `completed` | Reject and preserve state |
| `active` / `paused` | `block` | Non-empty reason | `blocked` | Reject empty reason or terminal source |
| `completed` / `blocked` | any except `set --replace` or idempotent `clear` | None | None | Reject; no silent resurrection |

Every successful state-changing transition updates `updated_at`, `last_action`, and history; the null-goal and already-cleared `clear` operations are explicit successful no-ops and do not update those fields. A state-changing transition must update `goal` and the surrounding state as one atomic file replacement. Goal transitions never edit `gate.approval` except that `resume` must explicitly preserve it.

## Implementation Plan

### Phase 1 — Add the deterministic state-transition seam

1. Create `scripts/orchestrate_goal_state.py` as a stdlib-only module/CLI.
   - Read one state JSON object from a path supplied by `--state` (defaulting to the repository root's `.ed3d/orchestrate-state.json` after bounded root resolution).
   - Validate the existing required orchestration shape without requiring optional legacy fields such as `review.history`.
   - Treat absent `goal` as legacy `null`; do not mutate on `show`.
   - Implement `show`, `set`, `pause`, `resume`, `clear`, `complete`, and `block` transitions with `--replace`, `--reason`, injectable clock/ID hooks for tests, and atomic temp-file replacement.
   - Preserve all unrelated top-level keys and preserve `gate.approval` exactly on every goal operation, especially `resume`.
   - Exit nonzero with a stable diagnostic and leave the file unchanged for malformed JSON, invalid goal shape, illegal transitions, missing text/reason, or failed completion preconditions.
   - Keep continuation-cap handling in this module; it must produce a blocked goal rather than silently looping.

2. Create `scripts/test_goal_state.py`.
   - Use temporary directories, an injected clock, and deterministic IDs; do not touch the working state or network.
   - Assert schema validation, RFC3339 timestamps, ID format, atomic preservation of unrelated keys, and exact `gate.approval` preservation.
   - Exercise every row of the transition table, including null-goal show/clear/no-goal rejections, all illegal-source cases, replacement refusal, explicit replacement, idempotent clear, terminal protection, empty block reason, and cap-to-block behavior.
   - Exercise migration of a legacy state with no `goal`, asserting legacy show and null clear are byte-identical no-ops while legacy set directly creates the first goal object; also cover malformed/partial JSON fail-closed behavior and no-write-on-error.

### Phase 2 — Add the operator command and integrate the loop

3. Create `plugins/ed3d-orchestrate/commands/goal.md`.
   - Document `/ed3d-orchestrate:goal` with no argument/show and the seven operations.
   - Resolve the repository root with the same bounded direct-read rule used by `commands/orchestrate.md`; never recursively search or request access outside the project.
   - Invoke the state-transition seam for mutations and display `text`, status, phase, plan path, `gate.approval`, review verdict, continuation count/cap, last action, block reason, and next action.
   - For `resume`, instruct the model to continue through the existing orchestrate resume path after the state write, but to re-present the approval checkpoint whenever `gate.approval` is not already explicitly granted. The command must state that goal resume never grants approval.
   - For `pause`, state that live Copilot work is not cancelled and that the pause takes effect before the next new dispatch.
   - For `set --replace`, require the operator to name the replacement explicitly; never silently discard a nonterminal goal.

4. Update `plugins/ed3d-orchestrate/commands/orchestrate.md`.
   - Add goal-aware reporting to auto-resume: show goal status/text/cap alongside the existing task/phase/plan/review report when a goal exists.
   - On an active goal, a bare auto-resume may continue only through the existing explicit-resume policy; it must not convert goal activity into builder approval.
   - Document the automatic complete/block mappings and the blocked-goal stop condition.

5. Update `plugins/ed3d-orchestrate/skills/orchestrating-the-loop/SKILL.md`.
   - Add the sibling goal schema and state separation rule to State Protocol.
   - Add the goal transition table and safe-boundary pause/resume rules in a dedicated Goal Lifecycle section before phase details.
   - Require `goal.status == active` before new dispatches; if paused or blocked, stop at the safe boundary and report the next operator action.
   - Preserve the existing `gate.approval` transition table verbatim in meaning and add an explicit invariant: `goal resume` cannot write `gate.approval: granted`; a pending approval remains pending.
   - Map SHIP/operator-accepted terminal verification to `complete_goal` semantics and circuit-break/unrecoverable/operator-stop paths to `block_goal` semantics without changing `review.*` ownership or the Branch B protocol-only gate.
   - Define explicit continuation accounting and cap behavior without describing a daemon or automatic Copilot restart.

6. Update `plugins/ed3d-orchestrate/README.md`.
   - Document the command surface, state schema, transition table summary, migration behavior, release limitations, and examples.
   - Clearly separate observed Polytoken behavior from this Copilot approximation, including the lack of `agent_goal_auto_accept`, `compact_context` parity, automatic goal driver, session-scoped persistence, and native mechanical enforcement.
   - Retain the existing Branch B statements and existing hook documentation; do not add a builder-gate hook or goal hook.

### Phase 3 — Deterministic replay and contract coverage

7. Create `scripts/test_goal_replay.py` and `scripts/fixtures/orchestrate-goals/` JSONL fixtures.
   - Define a small synthetic goal-event seam, explicitly not raw Copilot `events.jsonl`.
   - Replay legal sequences for set→pause→resume, set→complete, set→block, clear→set, and explicit replace.
   - Replay illegal sequences for resume without pause, complete before SHIP, dispatch while paused/blocked, silent active replacement, stale approval grant, malformed goal, cap exhaustion, post-terminal resurrection, and null-goal clear/no-op behavior.
   - Replay a review circuit-break hold followed by operator-accepted SHIP (goal remains active at the hold, then completes), and a circuit-break followed by operator rejection/stop (goal becomes blocked).
   - Require fixture-set parity and compare deterministic final state/verdicts.
   - Include a fixture proving `goal resume` preserves `gate.approval: "pending"` and cannot authorize a builder event.

8. Create `scripts/test_goal_command_contract.py` as a stdlib-only source contract test.
   - Read `plugins/ed3d-orchestrate/commands/goal.md`, `commands/orchestrate.md`, the orchestrating skill, and the README.
   - Assert every command operation and option is documented, bounded direct-read discovery is required, the required show fields are named, pause does not cancel live work, goal resume never grants approval, and the Polytoken/Copilot fidelity boundary is explicit.

9. Extend existing contract tests rather than weakening them:
   - `scripts/test_context_handoff_protocol.py` and `scripts/test_context_handoff_documentation.py`: assert that goal resume is described as separate from approval and that no Branch B/mechanical claim is introduced.
   - `scripts/test_orchestrate_event_replay.py`: retain all existing approval fixtures unchanged; add only a documented negative/compatibility assertion if the goal seam needs to prove that goal events do not alter the existing gate replay.
   - `scripts/test_context_handoff_scope.py`: update the release allowlist/docstring/output from 0.5.0 to 0.6.0 and enumerate these exact new paths: `plugins/ed3d-orchestrate/commands/goal.md`, `scripts/orchestrate_goal_state.py`, `scripts/test_goal_state.py`, `scripts/test_goal_replay.py`, `scripts/test_goal_command_contract.py`, plus the prefix `scripts/fixtures/orchestrate-goals/`; continue to reject `hooks.json`, existing hook scripts, facets/transclusion, and unrelated plugins.
   - `scripts/test-dispatch-protocol.py`: update its hard-coded plugin/catalog/changelog/README/ROADMAP release needles from 0.5.0/2.2.0 to the planned 0.6.0/2.3.0 values and add goal-command/version synchronization assertions.
   - `scripts/validate_plugins.py`: include `commands/goal.md` in strict command/frontmatter and policy validation without putting model pins or unsupported frontmatter in it.

### Phase 4 — Documentation, release metadata, and integration verification

10. Update the exact terminal owners before release documentation. The implementation/scope contract must enumerate the exact new paths `plugins/ed3d-orchestrate/commands/goal.md`, `scripts/orchestrate_goal_state.py`, `scripts/test_goal_state.py`, `scripts/test_goal_replay.py`, `scripts/test_goal_command_contract.py`, and the prefix `scripts/fixtures/orchestrate-goals/`; all other new paths require an explicit plan amendment before implementation:
    - In `plugins/ed3d-orchestrate/skills/orchestrating-the-loop/SKILL.md`, the existing Phase 6 SHIP/operator-accepted path owns the `completed` transition after terminal review verification.
    - In `plugins/ed3d-orchestrate/skills/adversarial-review/SKILL.md`, the `Parse the Verdict, Commit the State` protocol-failure branch (steps 2–3) owns protocol-failure history writes; the `FIX-FIRST` circuit-break branch (steps 121–124) owns the nonterminal hold and then the operator decision mapping: accepted/resolved writes SHIP then completes the goal, while rejected/stop blocks it.
    - In `plugins/ed3d-orchestrate/skills/orchestrating-the-loop/SKILL.md`, the State Protocol recovery rule and Phase 4 pre-dispatch checks own malformed/partial state and blocked dispatch handling; they must write `goal.block` with the concrete diagnostic reason before stopping, without changing `gate.approval` or `review.*` ownership.
    - In `plugins/ed3d-orchestrate/commands/orchestrate.md`, the auto-resume refusal/checkpoint branch owns explicit operator stop/abort mapping; do not invent a hook-level terminal writer. Each owner must complete its existing review/gate write first, perform the goal transition as the next atomic replacement, re-read/verify both blocks, and only then report or stop.

11. Update release/documentation files:
   - `plugins/ed3d-orchestrate/.claude-plugin/plugin.json`: bump to `0.6.0` and add a `goals` keyword if the catalog convention permits it.
   - `.claude-plugin/marketplace.json`: synchronize the `ed3d-orchestrate` entry to `0.6.0` and bump the catalog version from `2.2.0` to `2.3.0` for this catalog change set.
   - `CHANGELOG.md`: add a top `ed3d-orchestrate 0.6.0` entry describing durable goals, explicit continuation, migration, and the non-goals around autonomous continuation/mechanical enforcement.
   - `ROADMAP.md`: mark the goal-feature work landed only after implementation/review, record the explicit-resume-only fidelity boundary, and retain the deferred builder-gate and session-watcher items.
   - Update any goal command/installation/state references in `plugins/ed3d-00-getting-started/commands/getting-started.md` only if the existing user-facing command inventory includes `ed3d-orchestrate` commands; do not alter frozen legacy command semantics.

12. Run the full offline verification set after implementation:
     - `python3 scripts/test_goal_command_contract.py`
    - `python3 scripts/test_goal_state.py`
    - `python3 scripts/test_goal_replay.py`
    - `python3 scripts/test_context_handoff_protocol.py`
    - `python3 scripts/test_context_handoff_documentation.py`
    - `python3 scripts/test_orchestrate_event_replay.py`
    - `python3 scripts/test_orchestrate_enforcement_branch.py`
    - `python3 scripts/test_orchestrate_agent_dependencies.py`
    - `python3 scripts/test_plan_artifact_contract.py`
    - `python3 scripts/test-dispatch-protocol.py`
    - `python3 scripts/validate_plugins.py`
    - `python3 plugins/ed3d-orchestrate/hooks/test-check-review-loop.py`
    - `python3 plugins/ed3d-orchestrate/hooks/test-adversary-write-guard.py`
    - `python3 scripts/test_context_handoff_scope.py <base-revision>`

13. Verify with a clean implementation diff that no `hooks.json`, existing hook script, facet/transclusion resource, or unrelated plugin was changed. The goal module's atomic state write must preserve the fields consumed by both existing hooks. Do not add a runtime hook, event watcher, service, or process supervisor in this release.

## Acceptance Criteria

- **AC.1:** A fresh state can create one active goal with validated text, a unique-format `goal_id`, RFC3339 UTC timestamps, default `max_continuations: 50` (matching the documented Polytoken default while remaining explicit-resume-only in Copilot), zero continuations, and an initial history record. Verified by `python3 scripts/test_goal_state.py`.
- **AC.2:** The complete legal/illegal transition table is implemented: pause/resume, explicit replacement, clear retirement, terminal completion/blocking, cap-to-block, and terminal protection. Verified by `python3 scripts/test_goal_state.py` and `python3 scripts/test_goal_replay.py`.
- **AC.3:** Goal lifecycle is separate from orchestration phase, review lifecycle, and builder approval; every goal mutation preserves `gate.approval`, and goal resume never grants pending approval. Verified by `python3 scripts/test_goal_state.py`, the pending-approval replay fixture in `scripts/test_goal_replay.py`, and `python3 scripts/test_context_handoff_protocol.py`.
- **AC.4:** `/ed3d-orchestrate:goal` exposes show/set/set --replace/pause/resume/clear/complete/block, reports the required state and next action, and uses bounded repository discovery. Verified by `python3 scripts/test_goal_command_contract.py` (new, stdlib-only) and `python3 scripts/validate_plugins.py`.
- **AC.5:** Legacy state files without `goal` remain readable without eager mutation: legacy `show` and null-goal `clear` are byte-identical no-ops, while legacy `set` directly creates the first goal object; malformed state/goal data fails closed with no partial write. Verified by `python3 scripts/test_goal_state.py`.
- **AC.6:** Existing terminal orchestration outcomes map deterministically: SHIP/operator-accepted SHIP completes the goal; a circuit-break holds an active goal pending the existing operator decision; operator rejection/stop and unrecoverable/protocol failures block it with durable reasons. Paused/blocked goals prevent new dispatches only at a safe boundary and do not claim to cancel live Copilot work. Verified by `python3 scripts/test_goal_replay.py` and targeted source-contract assertions in `scripts/test_goal_command_contract.py`.
- **AC.7:** Existing plan-review approval semantics remain unchanged: plan review writes pending, a later explicit operator authorization grants approval immediately before builders, bare resume does not grant, and no goal operation creates a grant. Verified by `python3 scripts/test_context_handoff_protocol.py`, `python3 scripts/test_context_handoff_documentation.py`, and `python3 scripts/test_orchestrate_event_replay.py`.
- **AC.8:** Existing hooks remain unchanged in behavior and Branch B remains protocol-only; no autonomous continuation hook, builder-gate hook, service, or event watcher is introduced. Verified by `python3 scripts/test_orchestrate_enforcement_branch.py`, both hook suites, and `python3 scripts/test_context_handoff_scope.py <base-revision>`.
- **AC.9:** Documentation distinguishes Polytoken 0.8.5 behavior from the Copilot approximation, records that 0.8.2–0.8.5 did not change goal semantics, and documents explicit-resume-only continuation plus the absence of `agent_goal_auto_accept` and `compact_context` equivalents. Verified by `python3 scripts/test_goal_command_contract.py`, `python3 scripts/test-dispatch-protocol.py`, and documentation inspection.
- **AC.10:** Release metadata is synchronized at `ed3d-orchestrate` `0.6.0`, catalog `2.3.0`, changelog, and roadmap, and the full offline validation suite passes. Verified by `python3 scripts/validate_plugins.py`, `python3 scripts/test-dispatch-protocol.py`, and the command list in Phase 4.

## Test Strategy

| Area | Named verification |
|---|---|
| State schema, validation, migration, timestamps, IDs, atomic preservation | `python3 scripts/test_goal_state.py` |
| Transition legality and terminal/cap behavior | `python3 scripts/test_goal_state.py` |
| Replay across clear, replace, pause, resume, complete, block, malformed, and stale approval sequences | `python3 scripts/test_goal_replay.py` plus every fixture under `scripts/fixtures/orchestrate-goals/` |
| Command surface, bounded root discovery, report fields, explicit replacement, and no autonomous claims | `python3 scripts/test_goal_command_contract.py` |
| Existing approval gate and goal-resume separation | `python3 scripts/test_context_handoff_protocol.py`, `python3 scripts/test_context_handoff_documentation.py`, `python3 scripts/test_orchestrate_event_replay.py` |
| Existing hook behavior and Branch B status | `python3 plugins/ed3d-orchestrate/hooks/test-check-review-loop.py`, `python3 plugins/ed3d-orchestrate/hooks/test-adversary-write-guard.py`, `python3 scripts/test_orchestrate_enforcement_branch.py` |
| Strict plugin/command frontmatter and version/catalog synchronization | `python3 scripts/validate_plugins.py`, `python3 scripts/test-dispatch-protocol.py` |
| Plan artifact and release path scope | `python3 scripts/test_plan_artifact_contract.py`, `python3 scripts/test_context_handoff_scope.py <base-revision>` |
| Builder/fixer dependencies | `python3 scripts/test_orchestrate_agent_dependencies.py` |

All new tests are stdlib-only, deterministic, offline, write only inside temporary directories, and do not interpret raw Copilot event logs. The replay tests are protocol seams, as the existing approval replay test explicitly documents; passing them does not claim native Copilot runtime enforcement.

## Documentation Strategy

- `plugins/ed3d-orchestrate/commands/goal.md` is the operator-facing command contract and documents every operation, safe-boundary behavior, migration response, and next action.
- `plugins/ed3d-orchestrate/commands/orchestrate.md` and `plugins/ed3d-orchestrate/skills/orchestrating-the-loop/SKILL.md` remain the authoritative resume, phase, approval, review, and terminal-owner documentation; they must describe goal state as separate from `gate.approval` and preserve the existing Branch B protocol-only wording.
- `plugins/ed3d-orchestrate/README.md` documents the schema, transition summary, migration policy, examples, release limitations, and the distinction between Polytoken 0.8.5 behavior and the explicit-resume-only Copilot approximation.
- `CHANGELOG.md` and `ROADMAP.md` record the release and its non-goals only after implementation and adversarial review land. `plugins/ed3d-00-getting-started/commands/getting-started.md` is changed only if its current user-facing inventory includes orchestrate commands.
- `scripts/test_goal_command_contract.py` checks the required user-facing wording, while `scripts/test-dispatch-protocol.py`, `scripts/validate_plugins.py`, and the scope test check synchronization and path boundaries.

## Review Strategy

Before implementation, this plan is reviewed by the repository's native `plan-reviewer` agent using the absolute plan path and repository root. The reviewer must verify the state machine, exact file grounding, migration behavior, every AC-to-test mapping, the explicit-resume fidelity boundary, and that no proposed file silently creates mechanical enforcement. If critical/high findings appear, revise this plan once and re-dispatch the reviewer once; if critical/high findings remain, stop for operator decision rather than dispatching builders.

After operator approval and implementation, the existing `adversarial-review` tumble-dryer reviews the committed range. It must inspect goal-state code/tests and the unchanged approval/hook boundaries, run the complete named suite, check malformed/stale/paused/blocked/terminal behavior, verify no silent gate grant, and confirm version/marketplace/changelog synchronization. Critical/high implementation findings are fixed and re-reviewed under the existing round cap; medium/low findings are reported. Goal completion is written only after the existing terminal review state is valid.

## Risks

- **Copilot has no daemon-owned goal driver:** An active goal cannot reliably restart a Copilot turn after process exit or automatically follow completed jobs from plugin files. The implementation must remain explicit-resume-only, state that limitation in command/README/changelog docs, and test that no hook/service/event watcher is introduced.
- **Prompt and command guidance are not runtime enforcement:** The existing plan-review handoff is Branch B protocol-only, and goal dispatch suppression is also partly procedural. The state-transition module reduces ambiguity but cannot stop an orchestrator that ignores its instructions. Keep the existing hooks unchanged and make no builder-dispatch identity claim.
- **Repository-vs-session mismatch:** Multiple Copilot sessions in one repository could race on one state file, while Polytoken goals are session-scoped. Use `goal_id`, atomic replacement, and explicit documentation; do not claim multi-session locking or exact session parity. A future plan may add concurrency control only with observed Copilot/session evidence.
- **Model-written orchestration state:** The existing skill, not a central application, owns most state transitions. The deterministic module must preserve unknown fields and fail closed on malformed goal data; the implementation review must inspect every state write for lost `review.*` or `gate.*` fields.
- **Hook coupling:** Both existing hooks walk up to and parse the shared state file. Their current behavior ignores `goal`, but a malformed whole-file rewrite could disable or distort review guardrails. Run both hook suites and review atomic-write/error paths; do not modify hook registration in this release.
- **Terminal mapping ambiguity:** SHIP, operator-accepted SHIP, circuit-break, protocol failure, and explicit stop have different existing review semantics. Implement mapping only at the existing owning terminal paths, require valid `review` terminal fields for completion, and preserve review history/nonce/consecutive-block invariants.
- **Migration and history growth:** Legacy state files omit `goal`, and append-only goal history grows over replacements. Treat legacy show and null clear as byte-identical no-ops; legacy set directly creates the first goal object; never rewrite on show, preserve history for audit, and document that history is bounded only by the number of explicit goal transitions; add a future archival decision rather than silently truncating it.
- **Version and scope drift:** The repository separately validates manifest/catalog versions, changelog/roadmap needles, command policy, and changed-path scope. Bump all required metadata together and update the scope test for the 0.6.0 path set before calling the release complete.
- **Polytoken documentation fidelity:** Claims about Polytoken must remain tied to official sources: P1 command reference, P2 tool reference, P3 managing-work/sessions pages, P4 configuration/changelog. The plan and later docs must distinguish documented behavior from inference and record the installed runtime as `polytoken 0.8.5`.

### External source index

- **P1 (official, accessed 2026-09-07):** <https://docs.polytoken.dev/reference/commands/> — `/goal` command surface: show, set, pause, resume, clear.
- **P2 (official, accessed 2026-09-07):** <https://docs.polytoken.dev/reference/tools/> — `propose_goal`, `read_goal`, `complete_goal`, `block_goal`, `compact_context`, and `agent_goal_auto_accept` reference.
- **P3 (official, accessed 2026-09-07):** <https://docs.polytoken.dev/using-polytoken/managing-work/> and <https://docs.polytoken.dev/using-polytoken/sessions/> — goal/job continuation and persistence across clear/compaction/rewind/session recovery.
- **P4 (official, accessed 2026-09-07):** <https://docs.polytoken.dev/reference/configuration> and <https://docs.polytoken.dev/changelog> — `max_continuations_per_goal`, `agent_goal_auto_accept`, `compact_context` in 0.8.4, and the 0.8.2–0.8.5 comparison. Installed runtime check: `polytoken 0.8.5`.
