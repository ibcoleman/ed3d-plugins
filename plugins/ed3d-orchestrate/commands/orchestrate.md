---
description: "Run the full ed3d-orchestrate loop on a task: scout-sweep research, plan document, plan-reviewer gate, builder fanout, adversarial tumble-dryer review, final report"
argument-hint: "[task-description]"
---

# Orchestrate

## Auto-resume mode

Before asking for a task, locate `.ed3d/orchestrate-state.json` with direct file reads only — never a search: inside a git repository, resolve the root with `git rev-parse --show-toplevel` and read `<root>/.ed3d/orchestrate-state.json`; outside one, check `.ed3d/orchestrate-state.json` in the current directory and, if absent, its immediate parent (only if still within the same project tree). Do not use recursive glob patterns or `find`-style searches, and never request access to directories outside the project — an unbounded walk-up prompts for `/` access (observed in 0.3.1's first live run).

If `$1` is `resume`, or if `$1` is empty and the valid state file passes the
validated in-progress checks (`phase: "execute" or "review"`, a non-empty
absolute existing `plan_path`, and a task matching the plan context) while
either preserving a plan-bound execute checkpoint for its pending approval or
resuming an active review, including an active `"PENDING"` review. The clean
fresh combination with no bound plan and `review.active: false` /
`review.verdict: "PENDING"` remains excluded:

1. Read the state file, then `cd` to the repository root you resolved it from — `/clear` preserves the shell's working directory (a live resume once ran from `docs/`), so make every subsequent git command and state-file write root-relative.
2. Report the recorded `task`, `phase`, `plan_path`, and review state to the operator in one short paragraph.
3. Read the plan document at `plan_path` (if set).
4. Engage the `orchestrating-the-loop` skill to continue from the recorded phase — do not restart or repeat completed phases.
5. **Resume does not grant approval; a bare auto-resume is refused.** Resuming is not, by itself, authorization to dispatch builders. If the state file records `gate.approval: "pending"` (or the field is absent, malformed, or partial), do not dispatch any builder — present the operator approval checkpoint (reply **continue**) and wait for the explicit authorization to be processed. Only after that authorization is recorded as `gate.approval: "granted"` in the state file — written in the same turn, immediately before the first builder dispatch — may builders start. Resuming into `phase: "execute"` with approval still `"pending"` re-presents the checkpoint rather than rolling into dispatch.

If `$1` is `resume` and no state file exists, say so and ask for the task. If `$1` is empty and no state file exists, ask the operator what they want accomplished before engaging the loop. If the state file records a completed loop (`review.active: false` and `review.verdict: "SHIP"`), report it as completed — task and round count from `review.history` — and ask for the new task instead of resuming.

## Reset and resume safety

- A **non-empty task argument always starts a fresh loop**. It never
  auto-resumes. Reset every task, plan, approval, SHA, and review field before
  planning: `task`, `plan_path`, `base_sha`, `head_sha`, `phase`,
  `gate.approval`, the `handoff` block, `review.max_rounds`, history, counters,
  and nonce. Existing plans and commits remain untouched; only the control
  plane is reset.
- An **empty invocation may resume only** when the state is valid and
  in-progress: `phase: "execute" or "review"`, a non-empty absolute `plan_path` that exists,
  and a task that matches the plan context. The unbound clean fresh combination
  with `review.active: false` and `review.verdict: "PENDING"` is not an
  in-progress loop; a plan-bound execute checkpoint and an active review,
  including active `PENDING`, remain resumable. Malformed, partial, legacy, or
  mismatched state fails closed and returns to the pending fresh baseline. The
  fail-closed rule is:
  malformed, partial, legacy, or mismatched state fails closed.
  A resume is valid only when task matches the plan context; malformed, partial,
  legacy, or mismatched state fails closed.
- A prior task's grant, plan path, SHA, nonce, history, or correction attempt
  cannot authorize a new task. A bare resume never grants approval.

When read-only planning prevents the reset write, phase 2 writes only the
plan.md artifact and records this permitted section in that artifact:

```markdown
## Orchestration Handoff
- reset_pending: true
- requested_task: <task text>
- prior_task: <task text or unknown>
- prior_plan_path: <absolute path or none>
- approval: pending
```

This is a **pending record, not authorization**. After planning, apply and
verify the reset against the task and absolute plan path, then change
`reset_pending: false` in control-plane handling before the later approval
write. If the record is missing, duplicated, or does not match, execution remains refused.

State transitions use the existing state file and verdict checklist. The hook
retains atomic temporary-file replacement, but that does not protect
concurrent model-mediated state edits. A verdict must be persisted and
re-read before it is reported; malformed state never becomes a fabricated
verdict.

## Ownership, clear, and resume

The canonical state includes `"ownership": {"status": "unowned",
"session_id": null, "transfer_from": null}` and `review.provenance` (null
before dispatch, then the current round's `dispatch_tool_call_id` and
`reviewer_agent_id`). Ownership statuses are `unowned`, `owned`,
`transfer_pending`, and `recovery_required`; missing or malformed ownership is
not an implicit owner claim. The stop hook reads both `sessionId` and
`session_id`.

`orchestrate resume` distinguishes these paths:

| Path | Required evidence and result |
|---|---|
| **same-owner continuation** | `owned` plus a live session matching `session_id`, the task, absolute plan, and phase; preserve approval and all review requirements without `transfer_pending` |
| **authorized ownership transfer** | `transfer_pending`, `transfer_from` equal to the old `session_id`, explicit `$1=resume`, a different live session, and matching task/absolute plan/phase; replace the owner, clear `transfer_from`, and preserve pending approval or active/PENDING review |
| **explicit legacy recovery** | missing/malformed ownership or `recovery_required`, explicit `$1=resume`, live identity, and matching task/absolute plan/phase; bind the new owner without inferring dispatch or verdict |

A different session without a valid transfer marker is an unauthorized
non-transfer session and is refused without mutation. An old owner may stop
while `transfer_pending`; a new session is silently allowed before its claim.
Missing event identity or malformed transfer emits the stable
`ownership-recovery-required` allow marker and leaves bytes unchanged.

### Executable ownership and provenance checklist

For a fresh task, read the live session identity before any phase transition.
When it is available, write `ownership.status: owned` with that exact
`session_id`, the current task, absolute plan, and phase, then re-read the
state file before dispatching or enabling review. If the session identity is unavailable,
leave the state unowned (or mark malformed legacy state
`recovery_required`), do not dispatch, do not claim ownership, and surface
`ownership-recovery-required`; never invent an identity from transcript text.

Before each adversary dispatch, set the current round and `review.verdict` to
`PENDING`, clear `review.provenance`, and persist `review.provenance` and
`review.recovery` as
`status: none`, `attempts: 0`, `marker: null`. Immediately after the parent
dispatch, persist `review.provenance.round` and
`dispatch_tool_call_id` from the matching task request/tool-start pair. After
`subagent.started` supplies the reviewer identity, persist
`reviewer_agent_id` in the same round and re-read all three bindings before
using the stop hook's reconciliation result. If any required identifier is
missing or crosses rounds, leave the owner enforcement active and use the
`review-reconciliation-unavailable` diagnostic; do not infer a verdict.

before `/clear` will create a different live session, the current owner must
write and re-read `ownership.status: transfer_pending` with
`transfer_from` equal to the current `session_id`, preserving task, absolute
plan, phase, approval, review, round, nonce, and history. `/clear` is only the
context handoff; it is not an ownership claim or approval. A resumed session
must process the explicit `resume` command, validate its live identity and
bindings, replace the owner, clear `transfer_from`, and only then continue.
Same-owner continuation does not write `transfer_pending`.

Review provenance is observational evidence: the stop hook accepts only a
current dispatch/start/reviewer-message/completion lineage and its exact
nonce-tagged two-line terminal verdict. It streams JSONL beyond 256 KiB and
ignores quoted, fenced, duplicate, trailing, stale, wrong-lineage, and
`tool.execution_complete` text. A valid owner with missing or unavailable
completed lineage remains blocked with `review-reconciliation-unavailable`;
normal active PENDING with no completed result remains ordinary enforcement.
The protocol permits one current-round reconciliation retry. The second
unavailable result writes `reconciliation_exhausted`, `attempts: 1`,
`review.active: false`, and `review.verdict: "PENDING"` in one transition.
Stopping is then allowed only with `review-reconciliation-unavailable` and
an explicit no-verdict operator choice. No verdict exists in that state and
no SHIP outcome is inferred.

If an adversary response has no parseable verdict, record one same-round
`protocol failure`/`PENDING` history entry and perform only the existing one
protocol re-dispatch. If that retry also has no verdict, persist
`reconciliation_exhausted`, `review.active: false`,
`review.verdict: "PENDING"`, `attempts: 1`, and the diagnostic marker in one
state transition. Report that no verdict exists, allow the stop only through
the exhausted diagnostic, and require an explicit operator choice to re-arm or abandon.
This exhausted protocol-failure path must never SHIP.

## Normal mode

$1 contains the task description. If it is empty or vague after the auto-resume check above, ask the operator what they want accomplished — do not guess a task.

1. **Verify the working directory and git baseline.** Confirm you are inside the repository where the work will happen. The loop requires a local git repository with at least one commit because adversarial review needs a valid `BASE_SHA..HEAD_SHA` range. If no git repo exists and the directory is empty or the task is to create a new project, initialize git and create an initial commit before research. If no git repo exists in a non-empty directory, ask before initializing. If a git repo exists but has no commits, create an initial commit before implementation. The loop maintains `.ed3d/orchestrate-state.json` in that repository's root — read it there directly (the guardrail hook does its own in-process walk-up from the working directory; that is its mechanism, not an instruction to you). If you are in the wrong place, `cd` to the right repository first.

2. **Engage the `orchestrating-the-loop` skill** (ed3d-orchestrate) and run it end-to-end for this task:

   Task: $1

3. Follow the skill exactly: research (scout-sweep) → plan document → plan-review gate → **operator approval checkpoint** → builder execution → adversarial review rounds → final report. The plan-review pass is followed by an explicit approval checkpoint before any builder dispatch: the orchestrator ends its turn and offers the two approval paths — reply **continue** to proceed in the same context, or `/clear` then resume with a fresh context. Maintain `.ed3d/orchestrate-state.json` at every transition, record the plan document's absolute path as `plan_path` as soon as it is written so resume can find it, record a valid `BASE_SHA` before builder execution so review has a real diff range, and write `gate.approval: "granted"` to the state file in the same turn, immediately before the first builder dispatch, only after the operator's explicit `continue`/resume authorization is processed — never dispatch while approval is `"pending"`, stale, malformed, or partial.

After all builders have reported, check the Copilot-native `### Outcome
Handoff` rows for every approved `AC.n`: status (`complete, incomplete, or
blocked`), changed location, and a behavior-specific command/result. A
suite-only claim is not completion. The first missing outcome gets one
correction attempt through the existing fixer; on success, persist
`handoff.status: "verified"`, preserve `correction_attempts: 1`, clear
`remaining_outcomes: []`, and re-read that state before review. A second
incomplete handoff is `blocked` and requires a concrete takeover/replan
decision; do not arm independent review while it remains unresolved. Only
after this check succeeds should `head_sha` be recorded and review armed.
