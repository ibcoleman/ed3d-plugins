# Goal

Prevent one Copilot session from blocking or mutating another session's
`ed3d-orchestrate` review loop, and prevent transcript text from being treated
as the current review verdict without reviewer-lineage evidence. Preserve
enforcement for the owning session, define an explicit `/clear` + resume
ownership transfer, and give legacy or identity-poor state a bounded recovery
path.

The design is grounded in the source at baseline commit `3693c41`, whose
production hook content is unchanged in the current checkout. The current
runtime evidence is the documented `agentStop`/`Stop` payload (`sessionId`,
`cwd`, transcript path, and stop metadata), observed Copilot JSONL events
(`subagent.started`/`completed`, `assistant.message`,
`tool.execution_complete`, `agentId`, and `toolCallId`), and the existing
`preToolUse` write-guard payload. Manifest version `0.5.0` is not used as
baseline or installation evidence.

# Implementation Summary

1. Add explicit owner and reviewer-lineage fields to the existing orchestration
   state contract. The owner is the parent Copilot session; reviewer lineage
   records the dispatch and response identifiers needed to recognize a current
   adversary result. A fresh loop starts unowned until the orchestrator records
   its current session identity; a review cannot claim stronger enforcement
   when that identity is unavailable.
2. Scope `check-review-loop.py` to the persisted owner. A non-owner stop event
   must allow without changing the shared counter or state, while the owner
   retains normal pending-review enforcement. The preToolUse payload has no
   parent-owner field, so the existing review-wide write guard remains intact
   and this plan explicitly does not promise unrelated child-session
   non-blocking there.
3. Replace the raw transcript substring scan with a conservative streaming
   JSONL lineage check. Only the existing two-line nonce-tagged terminal
   verdict block in the expected reviewer assistant message, joined to the
   current dispatch and its completion, can trigger the uncommitted-verdict
   block. Quoted examples, prompts, file reads, tool-result content, and
   stale dispatches do not qualify; the parser retains bounded state rather
   than a transcript tail.
4. Document and replay an explicit clear/resume transfer: the old owner marks
   a transfer pending, the resumed session claims ownership explicitly, and
   approval/review requirements remain intact. Same-owner continuation and
   explicit legacy rebind are separate command paths. Missing ownership
   identity uses an explicit recovery-required allow path; unavailable
   reviewer reconciliation gets one bounded current-round retry and an
   observable exhausted state if it still cannot be proven, never silent
   success or repeated blocking as the recovery mechanism.

This remains a targeted hook/protocol change. It does not add a generic state
machine, a new builder-dispatch hook, a universal lock for model-mediated
writes, or a deployment/publication change. The explicit scope decision is
that owner isolation covers `agentStop`/`Stop` state blocking and mutation;
the existing review-wide preToolUse write guard is retained because its
payload cannot identify the parent session.

# Implementation Plan

## 1. Extend the state and ownership contract

Target files:

- `plugins/ed3d-orchestrate/commands/orchestrate.md`
- `plugins/ed3d-orchestrate/skills/orchestrating-the-loop/SKILL.md`
- `plugins/ed3d-orchestrate/skills/adversarial-review/SKILL.md`
- `plugins/ed3d-orchestrate/README.md`
- `scripts/test_orchestrate_event_replay.py`

Changes:

- Add an `ownership` block to the canonical state:

  ```json
  "ownership": {
    "status": "unowned",
    "session_id": null,
    "transfer_from": null
  }
  ```

  Allowed statuses are `unowned`, `owned`, `transfer_pending`, and
  `recovery_required`. New-task reset uses `unowned` with null identities.
  The `ownership` block is always present; `session_id` and
  `transfer_from` are explicitly `null` when unused. `review.provenance` is
  explicitly `null` before dispatch and is not itself an ownership failure.
- Add a `review.provenance` block containing the current review round,
  reviewer dispatch `tool_call_id`, and `reviewer_agent_id` when the runtime
  supplies them. `tool_call_id` becomes available in the parent
  `assistant.message.data.toolRequests[].toolCallId` and
  `tool.execution_start.data.toolCallId`; `reviewer_agent_id` becomes
  available in `subagent.started.agentId` before the reviewer can complete.
  The orchestrator persists the dispatch ID before relying on reconciliation,
  then persists the reviewer agent ID after the matching start event. These
  fields are evidence bindings, not authentication claims. Missing,
  duplicated, or cross-round links affect reconciliation only; they never
  change a valid owner's enforcement decision.
- Add a compact `review.recovery` block:

  ```json
  "recovery": {
    "status": "none",
    "attempts": 0,
    "marker": null
  }
  ```

  `status` is `none`, `reconciliation_retrying`, or
  `reconciliation_exhausted`; `attempts` is `0` or `1`; and `marker` is
  either `ownership-recovery-required`,
  `review-reconciliation-unavailable`, or `null`. Fresh and ordinary
  in-flight review state uses `none`. The block is audit state, not a second
  verdict and not an ownership identity.
- Use these exact state transitions:

  | State | Required fields | Allowed transition |
  | --- | --- | --- |
  | fresh | `ownership.status=unowned`, null session, `review.provenance=null`, `review.recovery.status=none`, inactive review | the command binds its current session before review |
  | owned | `ownership.session_id` and current task/plan binding | owner sets `transfer_pending` before `/clear`; a new task resets |
  | transfer pending | old owner remains in `session_id`; `transfer_from` equals it; task/plan binding intact | only the command's validated explicit `orchestrate resume` claim replaces `session_id`; old-owner stop is allowed without mutation |
  | malformed transfer | `status=transfer_pending` but missing/mismatched `transfer_from` | recovery-required allow; no claim or counter transition |
  | recovery required | malformed/missing owner or invalid binding; `review.active` is not an enforcement claim | explicit rebind validates task, plan, phase, and session; then clears `transfer_from` and returns to `owned`; no counter/verdict transition |

  An active review's provenance, when available, is:

  ```json
  "provenance": {
    "round": 1,
    "dispatch_tool_call_id": "call_dispatch",
    "reviewer_agent_id": "agent-reviewer"
  }
  ```

  `dispatch_tool_call_id` is persisted immediately after the parent task
  dispatch is emitted; `reviewer_agent_id` is persisted after
  `subagent.started`. `subagent.completed` confirms the same dispatch before a
  transcript marker can reconcile. A missing reviewer result is normal
  `PENDING` review, not missing provenance: the owner still receives ordinary
  active-review enforcement, while the hook simply has no stale-verdict
  reconciliation signal yet.
- Apply this precedence when ownership and reconciliation evidence disagree:

  | Condition | Hook outcome | Recovery meaning | Required action |
  | --- | --- | --- | --- |
  | Owner identity, event identity, or ownership binding is absent/malformed | supported `allow` with `ownership-recovery-required`; state bytes unchanged | ownership is unknown | explicit `orchestrate resume` rebinds the current session and task; no review dispatch is inferred |
  | Valid owner, review just armed, dispatch not emitted, or dispatch/start/completion is not yet due | ordinary active-review enforcement; no transcript reconciliation | normal `PENDING` review, not recovery | continue the existing dispatch; do not repair or clear provenance |
  | Valid owner, but a completed-result check cannot prove the required lineage because fields are malformed, cross-round, duplicated, out of order, or unavailable after a complete scan | ordinary owner enforcement with a `review-reconciliation-unavailable` diagnostic marker; state is unchanged except the normal block counter | reconciliation evidence is unavailable | use the existing adversarial-review resume-reconciliation/re-arm checklist; repair or re-dispatch the current review without fabricating a verdict; the safety cap is emergency protection rather than the recovery mechanism |
  | Valid owner and a complete, current lineage with the valid terminal verdict block | existing verdict-reconciliation behavior | current reviewer result is proven | commit the parsed result through the existing verdict checklist |

  The hook never converts a valid owner's unavailable reviewer evidence into
  an allow decision. The command-level re-arm/reconcile procedure clears or
  repairs the reviewer binding explicitly, while an absent owner identity
  remains the separate ownership-recovery allow path.
- Use this command/skill recovery transition table consistently in
  `commands/orchestrate.md`, `skills/orchestrating-the-loop/SKILL.md`, and
  `skills/adversarial-review/SKILL.md`:

  | Path | Entry evidence | State action | Dispatch/retry rule | Exhausted outcome |
  | --- | --- | --- | --- | --- |
  | same-owner continuation | `ownership.status=owned`; live command session equals `ownership.session_id`; matching task/absolute plan/phase | preserve owner, transfer fields, approval, round, nonce, history, and review requirements | run existing resume reconciliation; if the current chain is unavailable, permit at most one current-round re-dispatch using the existing protocol retry budget | write `review.recovery.status=reconciliation_exhausted`, `attempts=1`, marker `review-reconciliation-unavailable`, set `review.active=false`, leave `review.verdict=PENDING`, and require an operator choice; never report SHIP |
  | authorized ownership transfer | `ownership.status=transfer_pending`; `transfer_from` equals the recorded old owner; explicit `$1=resume`; live new session identity; matching task/absolute plan/phase | replace `session_id`, clear `transfer_from`, set `status=owned`, preserve approval/review requirements, and clear only a completed transfer marker | continue the preserved review; no verdict is inferred and no extra recovery retry is granted | same as the current review; transfer does not consume or reset the reconciliation retry budget |
  | unauthorized non-transfer session | a different live session with no valid transfer marker, or a resume with task/plan/phase mismatch | no state mutation, no owner claim, no dispatch | refuse inheritance; do not enter same-owner reconciliation | observable refusal, not ownership recovery and not a verdict |
  | explicit legacy recovery | ownership block absent/malformed or `status=recovery_required`; explicit `$1=resume`; live current session identity; matching task/absolute plan/phase | bind the current session as owner, normalize the ownership block, set `status=owned`, preserve review/approval requirements, and set recovery status to `none` | no dispatch is inferred by the bind; continue only through the normal review protocol | if live identity is unavailable, remain unchanged and surface `ownership-recovery-required`; no silent claim |

  `orchestrate resume` is the actual command entry for same-owner
  continuation, authorized transfer, and legacy recovery; the command
  distinguishes the paths by the persisted ownership status and live session
  identity rather than by synthetic replay input. A same-owner resume does
  not require `transfer_pending`; a different session does. The
  `reconciliation_exhausted` state is deliberately nonterminal: it allows
  the session to stop without claiming approval, and a later explicit
  same-owner `orchestrate resume` starts one fresh reconciliation attempt
  under the same one-attempt budget. Abandonment or operator-approved
  re-planning is an explicit operator decision, never an inferred verdict.
- The command entry receives task/resume intent as `$1` and reads the
  repository state directly; it does not receive a synthetic replay event.
  The current session identity must therefore come from the live Copilot
  session context when the command binds ownership. The `agentStop`/`Stop`
  hook independently receives `sessionId` or `session_id` and compares it to
  the persisted owner. If either integration cannot provide identity, the
  state enters `recovery_required` and no owner claim is inferred.
- Require the owner to persist `transfer_pending` before `/clear` when a
  different session will resume. A same-owner resume does not need that marker;
  it continues the owned state and runs resume reconciliation. An authorized
  transfer may claim ownership only when the state is transfer-pending and
  the task/plan/phase binding still matches. For `phase: execute`, approval
  remains pending and explicit `continue` is required again. For
  `phase: review`, the active review, round, nonce, history, SHAs, and
  pending verdict requirements remain; transfer does not create a verdict or
  approval.
- Update `commands/orchestrate.md` with the command-entry transition table.
  While `transfer_pending`, the old owner's stop is allowed without a counter
  mutation so `/clear` can complete. A resumed command may claim only after
  its direct state read is being processed for the explicit `resume`
  command argument, matching task and absolute plan, a valid phase/review
  binding, and its own session identity. The command then follows exactly
  one of same-owner continuation, transfer claim, or legacy rebind; a
  different session without a valid transfer marker is refused without
  mutation. The transfer claim writes the new owner and clears
  `transfer_from` before continuing; it preserves `gate.approval: "pending"`
  in execute and preserves review active/PENDING, round, nonce, history, and
  SHAs in review.
- Extend the referenced `orchestrating-the-loop` and `adversarial-review`
  checklists with the recovery table's one-attempt rule. A valid owner first
  gets one complete streaming reconciliation attempt. If the required chain
  remains unavailable, the existing review protocol may re-dispatch the
  current round once, consuming the same bounded protocol-retry budget; it
  must not start a second recovery budget or use the stop cap as recovery.
  On a second unavailable result, write
  `review.recovery.status="reconciliation_exhausted"`,
  `attempts=1`, `marker="review-reconciliation-unavailable"`,
  `review.active=false`, and `review.verdict="PENDING"` in one state
  transition, then report that no verdict exists and require an explicit
  operator choice to re-arm or abandon. A later same-owner `orchestrate
  resume` may clear the exhausted block, reset `attempts` to `0`, and re-arm
  exactly one fresh attempt; it never fabricates SHIP. The existing
  `verdict=PENDING means an adversary is in flight` invariant must document
  this explicit exhausted exception: `review.active=false` plus
  `reconciliation_exhausted` means no dispatch is in flight and no verdict
  exists.
- Define legacy recovery: state without an ownership block is not treated as
  owned. Explicit `orchestrate resume` from an identity-bearing session,
  with matching task and absolute plan, binds that session and preserves the
  pending approval/review requirements; it does not infer a dispatch or
  verdict. If identity is unavailable, the state remains unchanged and the
  operator receives the supported `ownership-recovery-required` outcome. A
  legacy state with a valid ownership block but no reviewer provenance follows
  the normal-PENDING or reconciliation-unavailable rows above; it is not
  silently treated as an ownership failure.
- Extend the existing replay seam with owner mismatch, legitimate transfer,
  transfer-without-claim, missing-identity, and legacy recovery cases. Keep
  its documentation explicit that it is protocol evidence, not native hook
  enforcement.

## 2. Scope production stop decisions and preserve write enforcement

Target files:

- `plugins/ed3d-orchestrate/hooks/check-review-loop.py`
- `plugins/ed3d-orchestrate/hooks/adversary-write-guard.py`
- `plugins/ed3d-orchestrate/hooks/test-check-review-loop.py`
- `plugins/ed3d-orchestrate/hooks/test-adversary-write-guard.py`

Changes:

- Parse `sessionId` and `session_id` from stop events. When an owned state
  receives a different session identity, allow without emitting a block and
  without writing `consecutive_blocks`; assert the state file remains byte-for-
  byte unchanged. The owner continues through the existing terminal-SHIP,
  active-review, cap, and counter-reset paths.
- Treat absent owner identity, absent event identity, malformed ownership, and
  legacy state without an ownership block as `recovery_required`: emit a
  supported allow decision with a stable recovery marker in its reason, do not
  mutate the state, and do not use the seven-block cap as recovery. A valid
  non-owner event remains a silent allow with no decision object. The explicit
  resume/re-arm protocol is the only way to restore ownership enforcement.
- Keep `adversary-write-guard.py`'s existing review-wide `call_` context
  behavior and tests. Its `preToolUse` stdin has `cwd`, child `sessionId`, and
  `toolCalls[]`, but no parent owner/session field; it cannot safely decide
  whether that child belongs to the owning parent. Do not weaken legitimate
  reviewer write enforcement or claim unrelated-child isolation that this
  payload cannot prove. Missing reviewer completion provenance does not
  disable this normal PENDING write guard.
- Preserve the existing fail-open behavior for malformed stdin and missing
  state, but make identity-loss behavior observable through the recovery
  reason and tests. Do not broaden the write guard to bash redirections or
  claim protection for payload fields the runtime does not provide.

The stop-hook decision matrix is:

| State / event | Output | State mutation |
| --- | --- | --- |
| `owned`, matching owner | existing normal enforcement | existing counter/terminal updates |
| `owned`, different owner | silent allow | none |
| `transfer_pending`, old owner | allow with no recovery requirement | none |
| `transfer_pending`, any other session before command claim | silent allow | none |
| `recovery_required`, or owner/event identity missing | allow with a stable `ownership-recovery-required` reason marker | none |
| valid owner with active `PENDING` but no completed reviewer result | existing ordinary pending-review block | existing counter update |
| valid owner with malformed/unavailable completed-result lineage | ordinary owner block with a `review-reconciliation-unavailable` diagnostic marker | existing counter update only |
| `review.recovery.status=reconciliation_exhausted` with a matching owner | supported allow with `review-reconciliation-unavailable` and no-verdict diagnostic markers | none |

The exact English around the recovery marker is not an API contract; the
machine-checkable contract is the supported `decision: "allow"` shape,
the `ownership-recovery-required` marker, and unchanged state bytes. The
`review-reconciliation-unavailable` marker is diagnostic only and does not
convert valid-owner enforcement into an allow. Normal pending review is
deliberately separate from both ownership recovery and unavailable
reconciliation evidence. The exhausted row is the sole explicit allow for
unavailable reconciliation, and it is not a success/SHIP outcome.

## 3. Replace substring verdict scanning with event-lineage reconciliation

Target files:

- `plugins/ed3d-orchestrate/hooks/check-review-loop.py`
- `plugins/ed3d-orchestrate/hooks/test-check-review-loop.py`

Changes:

- Stream the transcript as JSONL records instead of scanning only the
  256 KiB tail or arbitrary bytes. Read one record at a time from the start
  of the file, retain only fixed-size parser state (the expected IDs,
  ordering flags, the latest terminal-block boolean, and bounded diagnostic
  counters), and never retain transcript contents or an event list. Ignore
  unrelated malformed lines; if a required matching link is malformed or
  absent after the complete scan, reconciliation is unavailable for this
  stop. That does not change ownership or silently allow a valid owner.
- Use this exact correlation contract:

  | Event | Required fields | Rule |
  | --- | --- | --- |
  | parent dispatch | `assistant.message.data.toolRequests[].toolCallId` or the matching `tool.execution_start.data.toolCallId` | the two observations of the same ID establish/confirm one dispatch for the current round; they are not duplicate dispatches |
  | `subagent.started` | `data.toolCallId`, `data.agentName`, top-level `agentId` | ID equals the dispatch ID; agent name is the adversary; agent ID becomes the expected reviewer ID |
  | reviewer message | top-level `agentId`, `data.content` | same reviewer ID; consider the latest such message after start and before completion |
  | `subagent.completed` | `data.toolCallId`, top-level `agentId` | same dispatch and reviewer IDs; this is the required completion boundary |
  | `tool.execution_complete` | any result fields | never used as verdict evidence; its text is arbitrary tool output |

  The accepted event-index sequence is dispatch → `subagent.started` →
  one or more reviewer messages → `subagent.completed`. The latest reviewer
  message must end with this exact two-line terminal verdict block, with no
  trailing non-empty content:

  ```
  VERDICT: SHIP [<current nonce>]
  has_critical_or_high: false
  ```

  or:

  ```
  VERDICT: FIX-FIRST [<current nonce>]
  has_critical_or_high: true
  ```

  The verdict and boolean must be a valid pair. A quoted, fenced, duplicated,
  nonce-mismatched, or trailing-content variant is not current evidence.
  Missing, mismatched, or out-of-order links are not a current result. The
  stream parser treats the matching `assistant.message` and
  `tool.execution_start` as one dispatch observation pair, and invalidates
  the candidate if a second dispatch ID or a reviewer message after
  completion appears in the same candidate chain. This is a direct JSONL
  parser in the stop hook, not the synthetic replay seam and not the
  unrelated transcript reducer.
- Ignore the same marker in `tool.execution_complete` result content,
  prompts, quoted/code-block examples, parent/orchestrator messages, file
  reads, stale dispatches, and records with a different nonce or reviewer
  lineage. The state-file verdict remains authoritative; the transcript only
  prompts the owner to reconcile an apparently uncommitted result.
- If the event stream lacks the identifiers needed for the chain, do not
  guess or convert a valid owner into an allow. Return the diagnostic
  `review-reconciliation-unavailable` outcome through the ordinary owner
  enforcement path and leave the state untouched except for its normal block
  counter. Only missing ownership/event identity uses the separate explicit
  `ownership-recovery-required` allow decision.
- Keep the existing diagnostic/no-forward wording and terminal-state checks.
  Test raw JSONL directly in the hook suite, including a completed chain with
  more than 256 KiB between dispatch and verdict; do not change the unrelated
  transcript reducer or create a second normalization path.

## 4. Update behavior-specific production-path tests and documentation

Target files:

- `plugins/ed3d-orchestrate/hooks/test-check-review-loop.py`
- `plugins/ed3d-orchestrate/hooks/test-adversary-write-guard.py`
- `scripts/test_orchestrate_event_replay.py`
- `scripts/test_context_handoff_documentation.py`
- `plugins/ed3d-orchestrate/README.md`
- `ROADMAP.md`

Changes:

- Add subprocess tests with runtime-shaped stop and pre-tool payloads and
  persisted-state assertions for positive and negative cases:
  owner blocks and increments; unrelated owner mismatch allows unchanged;
  transfer-pending old owner allows unchanged; new session before claim
  allows unchanged; claimed new owner enforces; malformed transfer emits the
  recovery marker and remains unchanged;
  quoted/tool-result/stale markers do not reconcile; genuine current reviewer
  lineage does reconcile; the exact two-line SHIP and FIX-FIRST blocks are
  accepted; quoted/fenced/duplicated/trailing variants are rejected; missing
  owner identity enters bounded ownership recovery; and malformed completed
  lineage remains an owner block with a reconciliation-unavailable marker.
  Include a streamed fixture with more than 256 KiB before the current
  reviewer result. Keep the existing write-guard positive case to prove
  normal PENDING enforcement; do not claim a separate unrelated-parent
  result that the payload cannot distinguish.
- Add clear/resume replay assertions showing that transfer preserves the
  pending approval or active review requirements, while a non-transfer resume
  and a new task cannot inherit ownership, nonce, history, or approval.
- Update README and roadmap language to distinguish the verified
  owner-scoped parent stop/state behavior and retained review-wide child write
  enforcement from the remaining runtime limitations:
  no parent-owner field is documented in the observed `preToolUse` payload,
  transcript lineage is observational and version-sensitive, and
  model-mediated concurrent writers are not protected by the hook's atomic
  replacement. Document the three resume paths, the single existing retry
  budget, and the explicit no-verdict exhausted-recovery outcome; do not
  describe review-wide child write enforcement as cross-session isolation.
- Keep installed plugin content stable during the self-hosted run. Do not
  bump manifests, publish, install, or alter frozen Claude resources.
- At handoff, review tracked and untracked changes explicitly against the
  approved target list with:
  `git status --short`,
  `git diff --name-status 3693c41..HEAD`, and
  `git ls-files --others --exclude-standard`.
  The approved source/test/documentation paths include the named fixture
  directory `scripts/fixtures/orchestrate-events/`. The plan document
  itself and `.ed3d/orchestrate-state.json` are separately reviewed
  orchestration artifacts, not implementation-scope surprises. The
  operator/reviewer compares those outputs to the approved paths and records
  any other extra path as a scope finding. Separately
  run
  `git diff --exit-code 3693c41..HEAD -- plugins/ed3d-orchestrate/.claude-plugin/plugin.json .claude-plugin/marketplace.json plugins/ed3d-orchestrate/agents plugins/ed3d-plan-and-execute/agents`
  and inspect that the installed plugin copy was not changed. This is an
  explicit tracked/untracked review, not an automated allowlist claim.

# Acceptance Criteria

1. **AC.1 Unrelated parent-session isolation is persisted and observable.**
   With an active owned review state, a representative non-owner
   `agentStop`/`Stop` event neither blocks nor changes the state file or
   `consecutive_blocks`; the matching owner still receives the intended
   active-review/terminal-state enforcement. The guarantee is explicitly
   limited to the parent stop/state path because `preToolUse` lacks a parent
   owner field. Verified by
   `python3 plugins/ed3d-orchestrate/hooks/test-check-review-loop.py` with
   before/after state assertions.
2. **AC.2 Normal pending review enforcement is preserved.** A valid owner
   with active `PENDING` review is still blocked by the existing stop hook,
   and the existing write guard still blocks observed `call_` reviewer
   contexts. Missing reviewer completion provenance does not disable either
   normal pending enforcement; malformed or unavailable completed-result
   lineage remains an owner block with a reconciliation-unavailable marker.
   Verified by the two production hook suites:
   `python3 plugins/ed3d-orchestrate/hooks/test-check-review-loop.py` and
   `python3 plugins/ed3d-orchestrate/hooks/test-adversary-write-guard.py`.
3. **AC.3 Only a genuine current reviewer result can reconcile a verdict.**
   A current nonce-tagged two-line terminal verdict block with a valid
   severity boolean, in the expected reviewer lineage plus its completion,
   blocks an uncommitted stop; the same marker in a quote, fenced example,
   prompt, file read, arbitrary tool result, stale dispatch, wrong lineage,
   duplicate block, or trailing content does not. The parser streams beyond
   the 256 KiB tail with bounded retained state. Verified through the
   production subprocess path by
   `python3 plugins/ed3d-orchestrate/hooks/test-check-review-loop.py`,
   including a fixture larger than 256 KiB.
4. **AC.4 Clear/resume has explicit, distinguishable continuation paths.**
   Same-owner continuation requires a live identity matching the persisted
   owner and does not require `transfer_pending`. Authorized ownership
   transfer requires `transfer_pending`, matching task/plan/phase, explicit
   `$1=resume`, and the new live identity; an unrelated session cannot
   inherit ownership. Explicit legacy recovery requires an identity-bearing
   `orchestrate resume` with matching task/absolute plan and preserves pending
   approval/review requirements without inferring a dispatch or verdict.
   Verified by `python3 scripts/test_orchestrate_event_replay.py` plus
   production subprocess cases in `test-check-review-loop.py` for same-owner,
   old-owner, authorized new-owner, unauthorized new-owner, pre-claim,
   post-claim, identity-poor, and malformed-transfer decisions.
5. **AC.5 Legacy and provenance-poor state have bounded recovery.** Missing
   ownership identity produces the explicit `ownership-recovery-required`
   allow outcome with no state mutation. Missing reviewer completion while a
   valid owner has an active `PENDING` review remains ordinary enforcement;
   unavailable completed-result lineage is an owner block with a diagnostic
   reconciliation marker, followed by at most one current-round
   re-dispatch using the existing protocol retry budget. A second unavailable
   result produces the observable
   `reconciliation_exhausted`/`review-reconciliation-unavailable` state,
   allows stopping without claiming a verdict, and requires an explicit
   operator choice to re-arm or abandon; it never relies on repeated blocking
   until the CLI cap. Verified by both production hook suites, the replay
   suite, and `python3 scripts/test_context_handoff_documentation.py`.
6. **AC.6 Scope and deployment remain stable.** The Branch B
   protocol-only builder handoff remains unchanged; no speculative builder
   gate, generic state framework, publication/version update, or installed
   plugin mutation is introduced. Verified by
   `python3 scripts/test_orchestrate_enforcement_branch.py`,
   `python3 scripts/validate_plugins.py`, and the explicit human review of
   `git status --short`, `git diff --name-status 3693c41..HEAD`, and
   `git ls-files --others --exclude-standard`, plus the protected-path diff
   command in the implementation plan. The review separately classifies the
   named fixture directory, plan artifact, and orchestration control state;
   it does not treat those approved artifacts as unexplained implementation
   changes.

# Test Strategy

- Exercise the production scripts as subprocesses with temporary repositories,
  state files, byte snapshots, and JSONL payloads. Do not use only static
  instruction assertions for AC.1–AC.3 or AC.5.
- Extend `test-check-review-loop.py` for owner mismatch, owner enforcement,
  missing ownership, event-level transcript parsing, quoted/tool-result
  false positives, stale lineage, genuine lineage, missing/duplicate/
  out-of-order links, exact two-line verdict-block variants, a streamed
  transcript larger than 256 KiB, and persisted counter assertions. Include
  checked-in test cases for both `sessionId` and `session_id` stop-event
  spellings, transfer-pending identity cases, exact
  `decision: "allow"` plus `ownership-recovery-required` assertions, and the
  owner-blocking `review-reconciliation-unavailable` diagnostic. Add
  exhausted-recovery assertions for the supported allow marker, no-verdict
  marker, `review.active=false`, `review.verdict="PENDING"`, attempts `1`,
  and unchanged ownership/review requirements.
  Include the native producer-shaped terminal pair
  `VERDICT: SHIP [<nonce>]` plus `has_critical_or_high: false`, and the
  corresponding FIX-FIRST/true pair; treat the parent task-request and
  `tool.execution_start` records with the same `toolCallId` as one dispatch.
  If a live runtime probe cannot provide stop identity, the test result must
  record the recovery-path decision rather than claiming owner enforcement.
- Keep `test-adversary-write-guard.py` focused on the existing positive
  `call_` write block and normal PENDING behavior; add a regression assertion
  that missing reviewer completion provenance does not disable it. Do not add
  an unsupported unrelated-parent isolation claim.
- Extend `test_orchestrate_event_replay.py` and its existing fixture directory
  for same-owner continuation, authorized transfer, unauthorized
  non-transfer refusal, explicit legacy rebind, unavailable-lineage retry,
  exhausted recovery, re-arm, task-binding, and approval-preservation
  ordering. Keep the synthetic/raw event distinction explicit.
- Extend `test_context_handoff_documentation.py` for the ownership states,
  transfer marker, same-owner versus transfer versus legacy resume paths,
  explicit one-attempt reconciliation retry, exhausted-recovery operator
  choice, and the absence of silent inheritance. Add named assertions for
  `commands/orchestrate.md`, `skills/orchestrating-the-loop/SKILL.md`, and
  `skills/adversarial-review/SKILL.md` so their recovery tables agree. Add
  named assertions for `ROADMAP.md` covering parent stop/state isolation,
  retained review-wide child write enforcement, unavailable parent-owner
  identity, and the Branch B boundary.
- Run the targeted commands:
  `python3 plugins/ed3d-orchestrate/hooks/test-check-review-loop.py`,
  `python3 plugins/ed3d-orchestrate/hooks/test-adversary-write-guard.py`,
  `python3 scripts/test_orchestrate_event_replay.py`,
  `python3 scripts/test_orchestrate_enforcement_branch.py`,
  `python3 scripts/test_context_handoff_documentation.py`, and
  `python3 scripts/validate_plugins.py`.
- Treat the known release-needle and historical portability suites as
  separate baseline checks; do not broaden this plan to repair them.

# Review Strategy

Use one bounded builder task covering the hook changes, focused tests, and
state/documentation contract. Before review, check the builder's
`### Outcome Handoff` against AC.1–AC.6; a green pre-existing suite is not
evidence of completion. Allow one directed correction only for missing
outcome evidence, then stop with a concrete recovery decision if the handoff
remains incomplete.

The adversary reviews the complete committed range independently. Its review
must specifically inspect: owner mismatch non-mutation, exact reviewer
lineage, quote/tool-result/stale verdict rejection, transfer preservation of
approval/review requirements, the distinction between same-owner continuation,
authorized transfer, unauthorized non-transfer refusal, and legacy rebind, the
single reconciliation retry budget, and the explicit exhausted no-verdict
state. It must not expand the change into a builder-gate or shared-writer
framework merely because those guarantees are unavailable.

# Risks

- **Explicit scope decision for the original isolation outcome:** the
  requested behavior “an unrelated session is not blocked” is fully
  implementable for parent `agentStop`/`Stop` events because those payloads
  carry the parent session ID. It is not safely implementable for arbitrary
  child `preToolUse` events because those payloads carry only the child
  context ID and tool calls, not the parent owner. The plan therefore delivers
  and tests parent stop/state isolation, retains the existing review-wide
  write guard, and reports child-session isolation as an unresolved runtime
  limitation rather than adding speculative infrastructure.
- **Plan-review blocker mapping:** incomplete state examples would prevent
  reliable clear/resume ownership transfer; conflating ownership recovery
  with unavailable reviewer evidence would either weaken owner enforcement or
  create repeated blocking; a line-only verdict rule would reject the
  existing reviewer output; a tail-only parser would miss ordinary completed
  reviews; missing transfer-hook cases would prevent proving old/new-owner
  decisions; placeholder recovery output would prevent observable bounded
  recovery; and an automated allowlist claim would overstate deployment-scope
  verification. The revision addresses each with a precedence table, the
  exact two-line verdict contract, a streaming bounded-state parser,
  production transfer/large-transcript cases, stable diagnostic markers, and
  explicit tracked/untracked review commands.
- **Runtime identity boundary:** the current `agentStop`/`Stop` payload
  documents a session identity, but the observed `preToolUse` payload does
  not expose a parent owner for arbitrary child contexts. The plan therefore
  leaves the existing write guard review-wide and refuses to claim stronger
  enforcement when that binding is unavailable.
- **Transcript schema drift:** the JSONL event chain and `agentId`/
  `toolCallId` relationship were observed locally, not guaranteed across all
  Copilot CLI versions. Missing or changed reviewer fields make
  reconciliation unavailable for a valid owner and use the diagnostic
  owner-block/re-arm path; only missing owner/event identity enters ownership
  recovery. The parser never falls back to raw text matching.
- **Procedural state ownership:** the hook can prevent non-owner counter
  mutation, but it cannot serialize all model-mediated writers. Atomic
  replacement remains an implementation detail, not a universal concurrency
  guarantee.
- **Clear/resume authorization:** a resumed session with the documented
  `orchestrate resume` command argument is the explicit entry for same-owner
  continuation, authorized transfer, and legacy rebind; the persisted
  ownership status and live identity distinguish them. If the current session
  ID is unavailable to the command, legacy recovery remains unchanged and the
  operator receives the recovery marker; no silent inheritance is allowed.
- **Reconciliation recovery budget:** unavailable completed lineage gets one
  full streaming reconciliation attempt and at most one current-round
  re-dispatch under the existing protocol retry budget. A second failure
  writes the explicit exhausted state (`active=false`, `verdict=PENDING`,
  `reconciliation_exhausted`) and allows stopping with a no-verdict marker.
  A later same-owner resume may explicitly re-arm one fresh attempt; the hook
  never uses repeated stop blocking or the safety cap as the recovery
  mechanism.
- **Legacy state:** pre-change state has no ownership/provenance fields.
  Missing ownership requires explicit rebind before enforcement; missing
  reviewer provenance with a valid owner preserves owner enforcement and uses
  the existing resume-reconciliation/re-arm checklist. This is safer than
  blocking unrelated sessions or trusting arbitrary transcript text.
- **Scope/deployment:** this plan changes source and tests only. Installed
  plugin stability and publication require a separate operator decision.
