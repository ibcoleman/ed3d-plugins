# Planning Brief: Polytoken-Inspired Goals for `ed3d-orchestrate`

**Status:** Planning input only — not an approved implementation plan.

**Next formal step:** Invoke `/ed3d-orchestrate:orchestrate` with this brief as the starting specification. The orchestrator must perform fresh repository research, write the canonical implementation plan to `docs/implementation-plans/<YYYY-MM-DD>-<slug>/plan.md`, send that plan through `plan-reviewer`, and stop for the existing operator approval checkpoint before any builder dispatch.

**Source brief:** Informal operator objective: “How would we implement the new Polytoken `goal` feature in our Copilot plugin?”

**Primary sources:**

- Polytoken commands: <https://docs.polytoken.dev/reference/commands/>
- Polytoken tools: <https://docs.polytoken.dev/reference/tools/>
- Polytoken work management: <https://docs.polytoken.dev/using-polytoken/managing-work/>
- Polytoken session lifecycle: <https://docs.polytoken.dev/using-polytoken/sessions/>
- Local Copilot portability audit: `docs/research/2026-09-01-polytoken-copilot-portability-audit.md`
- Current orchestrator contract: `plugins/ed3d-orchestrate/skills/orchestrating-the-loop/SKILL.md`

**Verification note (2026-09-07):** The installed runtime reports `polytoken 0.8.5`. The official changelog confirms that `/goal` and the goal driver predate the 0.8.2–0.8.5 release window; none of those four releases changes the goal command surface or goal-driver semantics. The goal contract below is therefore treated as current Polytoken 0.8.5 behavior, while the version-specific changes relevant to long-running work are recorded in Section 2.

## 1. Objective

Design and, after formal plan approval, implement a Copilot-native approximation of Polytoken’s saved-session `goal` feature for `ed3d-orchestrate`.

The feature should let an operator maintain one durable, inspectable objective across long-running orchestration work, context clears, explicit resumes, review pauses, and terminal completion or blockage. It should make goal state visible without weakening the existing plan-review-to-builder approval boundary.

The implementation should reuse the existing `.ed3d/orchestrate-state.json` state file rather than introduce a second goal database.

## 2. What Polytoken provides — observed behavior

The following is the observed contract from the current Polytoken documentation. The formal implementation plan must re-check these sources before treating any detail as an exact compatibility requirement.

### User commands

Polytoken documents:

- `/goal` — show the current goal
- `/goal set <text>` — set a goal
- `/goal pause` — pause goal continuation
- `/goal resume` — resume a paused goal
- `/goal clear` — clear the current goal
- `/todo` / `/todos` — inspect the retained session todo list
- `/jobs` / `/job` — inspect retained background jobs

### Model-facing tools

Polytoken documents:

- `propose_goal` — propose a goal and normally ask the operator to approve it
- `read_goal` — read the active goal and goal-file content
- `complete_goal` — move the goal to a terminal completed state and stop continuation
- `block_goal` — move the goal to a terminal blocked state and stop continuation

It also provides session todo tools and background subagent/job tools.

### Persistence

Polytoken sessions are durable records on disk. Compaction and clearing change context, not the underlying session history. Todos survive compaction and clear; rewind restores todos to the rewound point; detach/reattach and crash recovery preserve the session record.

Polytoken’s saved goal is persisted in the session record and a Markdown goal file. Exact goal-file format and all lifecycle details are not fully described in the public pages; do not assume undocumented internals.

### Continuation

An active goal can drive automatic continuation. The goal driver pauses continuation while a top-level shell or subagent job is live and resumes after that job finishes when notification auto-drain is enabled. A service job does not pause continuation. Configuration includes a continuation cap; setting the cap to zero disables automatic continuation while retaining goal metadata/tools.

The 0.8.2–0.8.5 release window did not introduce or change this goal behavior. The relevant adjacent 0.8.x additions are:

- `compact_context` (0.8.4), which lets an agent compact context immediately with a verbatim continuation directive; it requires at least 40% context usage and may reference `@skill:name`.
- More robust provider retry/stream-recovery behavior and improved turn interruption, which help long-running sessions but do not create a Copilot goal driver.
- Rewind support for facet-switch/plan-handoff boundaries (0.8.4), which has no direct Copilot equivalent.

Polytoken also exposes `daemon.goal_driver.agent_goal_auto_accept`: when enabled, model-proposed goals do not require operator approval; when disabled, they do. Copilot has no equivalent native goal-approval overlay, so the proposed Copilot MVP remains explicitly operator-driven and must not imply parity with this setting.

## 3. Existing `ed3d-orchestrate` foundation — observed local behavior

The current orchestrator already provides the durable workflow substrate:

- `.ed3d/orchestrate-state.json` is the repository-local audit/state file.
- State includes `task`, `phase`, `plan_path`, `base_sha`, `head_sha`, `gate.approval`, and the review block.
- The command can discover an in-progress state file and resume from the recorded phase.
- `/clear` plus resume preserves the plan and state on disk.
- The plan-review gate writes `gate.approval: pending` and ends the turn.
- A later explicit operator authorization writes `gate.approval: granted` immediately before the first builder dispatch.
- Bare auto-resume does not grant builder authorization.
- Review completion is represented by `review.verdict`, `review.active`, and `review.history`.
- Circuit-break and operator-decision paths already provide a model for blocked work.
- Branch B is protocol-only: no builder-dispatch enforcement hook is currently shipped because current Copilot evidence does not prove a safe pre-start matcher.

The formal plan must preserve these existing semantics.

## 4. Proposed Copilot goal model

Add a `goal` object to the existing state schema, keeping goal lifecycle separate from phase, review, and builder approval:

```json
{
  "goal": {
    "text": "Implement and validate the goal feature for ed3d-orchestrate",
    "status": "active",
    "continuations": 0,
    "max_continuations": 5,
    "created_at": "2026-09-07T00:00:00Z",
    "updated_at": "2026-09-07T00:00:00Z",
    "last_action": "set",
    "block_reason": null
  }
}
```

The formal plan must choose and document the final schema, timestamp format, identity/nonce rules, history policy, and migration behavior for older state files. The example is illustrative, not a locked schema.

### State separation requirement

Do not overload `gate.approval` with goal lifecycle meaning:

| State | Meaning |
|---|---|
| `goal.status` | Whether the durable objective is active, paused, completed, blocked, or cleared |
| `phase` | Which orchestration phase is in progress |
| `gate.approval` | Whether the operator authorized the reviewed plan to enter builder execution |
| `review.*` | Adversarial review lifecycle and verdict |

In particular:

> Resuming a goal must never implicitly grant `gate.approval`.

A paused goal can resume into a pending approval checkpoint and still require an explicit `continue` authorization.

## 5. Proposed command surface

The formal plan should evaluate a command such as:

```text
/ed3d-orchestrate:goal
/ed3d-orchestrate:goal set <description>
/ed3d-orchestrate:goal pause
/ed3d-orchestrate:goal resume
/ed3d-orchestrate:goal clear
/ed3d-orchestrate:goal complete
/ed3d-orchestrate:goal block <reason>
```

Required behavior to design and test:

- `goal` shows goal text, status, phase, plan path, approval state, review verdict, continuation count, and next action.
- `goal set` creates/replaces a goal only under an explicit replacement policy; it must not silently discard active work.
- `goal pause` prevents new dispatches and records the pause without pretending to cancel already-running Copilot work.
- `goal resume` reactivates a paused goal and re-enters the existing state-driven resume path; it must not grant builder approval.
- `goal clear` retires the goal in an auditable way rather than deleting state needed for recovery or review hooks.
- `goal complete` is allowed only from a valid terminal or explicitly operator-accepted state.
- `goal block` records a durable reason and prevents silent continuation until an operator acts.

The final command names and whether `complete`/`block` belong in a separate command or are inferred from existing orchestrate terminal paths are open design decisions for the formal plan.

## 6. Continuation design and fidelity boundary

The current Polytoken 0.8.5 implementation adds useful session-side continuation support, especially `compact_context` and improved job/turn handling, but these are Polytoken runtime capabilities rather than Copilot plugin capabilities. The 0.8.2–0.8.5 changes provide no new Copilot evidence that would alter the boundary below.

Copilot plugins do not currently provide Polytoken’s daemon-owned automatic goal driver. The MVP must therefore distinguish two concepts:

1. **Durable goal state:** feasible now through `.ed3d/orchestrate-state.json` and explicit commands.
2. **Autonomous continuation after a turn/job:** not yet proven feasible through Copilot plugin surfaces.

The lowest-risk MVP should use explicit continuation through the existing orchestrate command/resume path. It may improve no-argument auto-resume, but it must not claim that an active goal automatically restarts Copilot after a session ends.

If a continuation cap is added, keep it separate from `review.max_rounds`:

- `goal.max_continuations` limits goal-driven resume attempts.
- `review.max_rounds` limits adversarial review rounds.

At the continuation cap, the workflow should stop and record a blocked/operator-decision state rather than looping silently.

## 7. Proposed formal planning workflow

The future formal planning pass should follow this sequence:

### Step A — Establish the goal

Treat this brief as the initial specification. Read it, inspect the current branch/repository state, and identify any active `.ed3d/orchestrate-state.json` before beginning unrelated work.

If the operator wants to use Polytoken semantics literally, the analogous Polytoken actions are `/goal set`, `propose_goal`, and `read_goal`. In Copilot, the equivalent is a task-specific `/ed3d-orchestrate:orchestrate` invocation plus this brief.

### Step B — Create research todos

Use bounded research tasks for:

- current orchestrator state/schema and all read/write paths
- current command and skill loading conventions
- Copilot command persistence and resume behavior
- existing state/contract/replay test patterns
- Polytoken goal semantics and documented limits

Research tasks should have explicit outputs and should not modify implementation files.

### Step C — Run bounded research/subagents

The Polytoken analogue is to use subagents for bounded pieces of work and jobs for observable background work. For the Copilot implementation, `scout-sweep` and the repository’s native agent dispatch are the closest available mechanisms.

The planner must distinguish:

- facts observed in the repository
- facts observed in current Polytoken documentation
- assumptions about Copilot behavior
- proposed design decisions

### Step D — Write the canonical implementation plan

After research, create exactly one canonical plan artifact:

```text
docs/implementation-plans/<YYYY-MM-DD>-<slug>/plan.md
```

The plan must contain, in order:

1. Goal
2. Implementation Summary
3. Implementation Plan
4. Acceptance Criteria
5. Test Strategy
6. Review Strategy
7. Risks

The plan should define the state machine and transition table before proposing prose edits. It must name exact files and commands and must not make automatic-continuation or mechanical-hook claims without evidence.

### Step E — Plan review

Dispatch the named `plan-reviewer` through Copilot’s native agent/subagent mechanism, using the current bounded dispatch policy. Fix critical/high plan findings once and re-review once. If critical/high findings remain, stop for operator decision.

### Step F — Operator approval checkpoint

When plan review passes:

- persist `phase: execute`
- persist `gate.approval: pending`
- end the turn
- present the plan-review result and approval paths
- do not dispatch builders in that turn

Only a later explicit operator authorization may write `gate.approval: granted` immediately before builder dispatch.

### Step G — Implementation and review

Only after approval should builders implement bounded tasks. The full work then follows the existing builder → adversarial review → terminal report process. Goal completion/blocking must be mapped to valid terminal state and must not bypass the review or approval invariants.

### Step H — Release

Before calling this an `ed3d` release, verify:

- state schema and migration behavior
- command and README documentation
- deterministic transition/replay tests
- existing hook and plugin validation suites
- version/marketplace/changelog synchronization
- explicit documentation of Copilot continuation limits
- adversarial review with no critical/high findings

## 8. Suggested MVP scope

The formal plan should consider this smallest useful slice:

- extend `.ed3d/orchestrate-state.json` with a documented `goal` object
- add a goal command with show/set/pause/resume/clear
- map existing SHIP/operator-accepted terminal paths to goal completion
- map circuit-break, explicit stop, and unrecoverable failures to blocked state
- add a continuation counter/cap without claiming daemon-driven continuation
- add deterministic state-transition and replay tests
- preserve the existing plan-review approval gate
- update README, state schema, roadmap, changelog, and release metadata

## 9. Explicit non-goals for the first release

The formal plan should treat these as out of scope unless new evidence changes the decision. The Polytoken 0.8.2–0.8.5 changes do not provide such evidence; in particular, they do not create a Copilot analogue for automatic continuation or native goal approval:

- a second goal database or global cross-repository goal store
- exact Polytoken daemon/session-driver parity
- autonomous Copilot restart after a turn or process exit
- model-proposed goals with native approval UI
- a new mechanical builder-gate hook
- relocation/removal of legacy builder/fixer resources
- resurrection of the legacy multi-file phase-file execution protocol
- porting `/flesh-it-out` solely for goal support

## 10. Open decisions for the formal planner

The formal plan must resolve or explicitly defer:

1. Is the goal repository-scoped, session-scoped, or both? The current state file is repository-scoped; Polytoken’s goal is session-scoped.
2. Does `goal set` replace an active goal, create a new goal ID, or require explicit clear first?
3. Should `goal clear` preserve a goal history in the state file?
4. What exact statuses are public: `active`, `paused`, `completed`, `blocked`, `cleared`?
5. Are `complete` and `block` commands necessary, or should existing terminal orchestrate paths own them?
6. Does goal pause take effect immediately when a builder/reviewer is already running, or only at the next safe boundary?
7. What is the default continuation cap, and how is it reported?
8. Is any Copilot hook/session event sufficiently reliable to improve continuation, or must the release remain explicit-resume-only?
9. What migration behavior applies to old state files without a `goal` object?
10. Should goal state be included in or excluded from the existing review hook’s fail-open behavior?
11. How should the formal plan document the Polytoken 0.8.5 verification date and distinguish stable goal semantics from adjacent 0.8.x runtime improvements?

## 11. Formal-plan acceptance expectations

Before implementation begins, the canonical plan should be able to demonstrate:

- a complete goal state/transition table
- no accidental coupling between goal resume and builder approval
- explicit handling of malformed, stale, paused, blocked, and terminal state
- deterministic tests for every legal and illegal transition
- clear separation between observed Polytoken behavior and Copilot approximation
- the observed Polytoken version is recorded as 0.8.5, with the 0.8.2–0.8.5 changelog comparison stating that goal semantics did not change
- `agent_goal_auto_accept` and `compact_context` are considered explicitly, including their lack of Copilot equivalents
- no claims of autonomous continuation or mechanical enforcement without current evidence
- preservation of the shipped Branch B protocol-only contract and existing explicit approval boundary
- exact release/version/changelog synchronization requirements
- a named adversarial review strategy

This brief is successful when a planner can use it to produce that implementation plan without guessing what the operator meant by “implement the Polytoken goal feature.”
