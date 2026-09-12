# ed3d-orchestrate

**EXPERIMENTAL. Copilot-first.** A Polytoken-style orchestration loop for GitHub Copilot CLI: scout-sweep research fanout → plan document → plan-review gate → builder fanout → adversarial "tumble dryer" review rounds with a hook-enforced backstop.

This plugin is written for Copilot CLI's native delegation. Its skills use Copilot-native dispatch prose (not Claude Code's XML `Task` blocks), and its agents ship as `*.agent.md`. It installs cleanly under Claude Code too — the guardrail hook fails open when no orchestration state file exists — but the workflow itself targets Copilot sessions.

**Agents and skills use different loaders.** Names that identify `*.agent.md` resources (including scouts, reviewers, builders, adversaries, and fixers) must be invoked through Copilot's native agent/subagent delegation mechanism; do not call the Skill loader for agent names. Use the Skill loader only for `SKILL.md` resources.

## The Loop

```
 /orchestrate "[task]"
     │
     ▼
 1. RESEARCH ──── scout-sweep: 2-4 researcher agents in parallel
     │            (codebase-investigator, internet-researcher, ...)
     ▼
 2. PLAN ──────── docs/implementation-plans/<date>-<slug>/plan.md
     │            (read-only phase; plan doc is the only write)
     ▼
 3. PLAN-REVIEW ─ plan-reviewer gate: fix critical/high, re-review
     │            once, unresolved -> operator decides
     ▼
 4. EXECUTE ───── task-implementor-fast builders, one bounded task
     │            each; independents parallel, dependents sequenced
     ▼
 5. TUMBLE DRYER  adversarial-review loop: adversary -> verdict ->
     │            fix critical/high -> re-review (max rounds, then
     │            operator circuit-breaker). agentStop hook blocks
     │            premature stops while the loop is active.
     ▼
 6. REPORT ────── per-phase summary, review history, final verdict
```

### Owner and reviewer-lineage state

The persisted contract includes `"ownership"` with `unowned`, `owned`,
`transfer_pending`, and `recovery_required` statuses, plus a `"provenance"`
object carrying `dispatch_tool_call_id` and `reviewer_agent_id` for the
current round. It distinguishes same-owner continuation, authorized
ownership transfer, and explicit legacy recovery. Missing identity uses
`ownership-recovery-required` without mutation. A bound but unavailable
completed result remains owner-blocked with
`review-reconciliation-unavailable`; after one retry the explicit
`reconciliation_exhausted` / no-verdict state allows an operator choice. The
diagnostic is `no verdict exists` in that state.
The preToolUse has no parent owner field, so child write enforcement remains
review-wide rather than claiming unrelated-session isolation.

## Agents and model selection

The Copilot-native `*.agent.md` twins intentionally omit a `model` frontmatter key. Dispatch is pinned-first on best-effort hard-coded IDs, while the twins preserve role descriptions and bodies from their Claude Code originals and remain directly Auto-compatible.

| Agent group | Role | Preferred dispatch |
|-------------|------|--------------------|
| `adversary` | Adversarial review | `gpt-6-astra` / `medium` |
| `plan-reviewer`, `task-implementor-fast`, `task-bug-fixer` | Plan gates, builders, and review fixes | `gpt-5.6-luna` / `high` |
| Research agents and `haiku-general-purpose` | Scouts | `gpt-5.6-luna` / `high` |

On each delegated dispatch, the preferred model/effort is attempted first. Only a visible pre-start rejection explicitly identifying model, account availability, or effort support triggers one fallback with both overrides omitted (Auto); ambiguity and any started dispatch are never retried as model fallback. Direct agent launches remain Auto-compatible.

Dispatched agents come from `ed3d-plan-and-execute`, `ed3d-research-agents`, and `ed3d-basic-agents`; install those plugins when using their roles.

The orchestrator is the main session — there is deliberately no orchestrator agent file. Start it with whatever model and account defaults are appropriate for the task.

## Model and effort defaults

Dispatch uses best-effort hard-coded model IDs and reasoning efforts: the adversary uses `gpt-6-astra` / `medium`, and every other orchestrated role uses `gpt-5.6-luna` / `high`. This is procedural pinned-first guidance, not a mechanically intercepted runtime feature. If Copilot visibly rejects the preferred model, account, or effort before any start signal, retry exactly once with both overrides omitted so Auto-only accounts continue to work; a started or ambiguous outcome is not retried as model fallback. Existing rate-limit and protocol-failure retries remain separate.

No agent frontmatter pins are added, so direct agent launches remain compatible with Auto-only accounts. A researcher started directly outside this orchestrated dispatch path therefore inherits the account/CLI default; configure per-agent defaults through Copilot's `/subagents` command or use an explicit native dispatch override when a direct launch must be pinned. The observed `claude-haiku-4.5` medium-effort rejection motivates the fallback; Copilot's dispatch-error semantics are otherwise unknown and require visible evidence before any fallback.

For direct adversary launches, select `ed3d-orchestrate:adversary` in `/subagents` and set `gpt-6-astra` with medium effort. Updating this repository's dispatch policy does not change an existing per-agent CLI preference or an installed plugin copy.

## State File

The loop maintains `.ed3d/orchestrate-state.json` in the working repository. It is both the audit trail (every transition is inspectable after the fact) and the input the guardrail hook reads.

```json
{
  "task": "add string-reversal CLI with tests",
  "plan_path": "/repo/docs/implementation-plans/2026-08-16-string-reverse-cli/plan.md",
  "base_sha": "3f2a1b9",
  "head_sha": "b7ddd28",
  "phase": "review",
  "gate": {
    "approval": "pending"
  },
  "handoff": {
    "status": "not_started",
    "correction_attempts": 0,
    "remaining_outcomes": []
  },
  "review": {
    "active": true,
    "round": 2,
    "max_rounds": 3,
    "verdict": "FIX-FIRST",
    "open_critical_high": [
      "high: src/cli.py:42 - panics on empty input"
    ],
    "consecutive_blocks": 1,
    "history": [
      {"round": 1, "verdict": "FIX-FIRST", "critical_high": 2, "advisory": 4}
    ],
    "nonce": "a1b2c3d4"
  }
}
```

- `phase`: `research` | `plan` | `execute` | `review`
- `base_sha` / `head_sha`: the commit range under review — recorded before builders run and after they commit; adversarial review refuses to start without both valid
- `review.verdict`: `PENDING` | `SHIP` | `FIX-FIRST`; final states are `SHIP` (including operator-accepted) or `review.active: false`
- `review.round` goes to `max_rounds + 1` when the circuit-breaker trips — that is the signal the hook uses to allow the stop
- `review.history`: append-only per-round verdict record; survives `/clear`+resume; ignored by the hook
- `review.nonce`: per-loop verdict tag (8 lowercase hex), generated when a review arms — including re-arms for a new loop — and survives `/clear`+resume; the guardrail matches rendered verdicts by it
- `handoff.status`: `not_started` | `pending` | `verified` | `blocked`; a first missing outcome permits one fixer correction attempt, a successful correction is persisted as `verified`, and a second incomplete handoff remains blocked before review
- `consecutive_blocks` counts blocks-since-last-progress: the hook increments it, the orchestrating skills reset it to 0 on every round/verdict transition; a terminal SHIP state with `consecutive_blocks != 0` is inconsistent and the hook will block the stop until it is repaired

## Review Policy (and how it differs from ed3d-plan-and-execute)

| Severity | Blocks shipping? |
|----------|------------------|
| critical | Yes — must fix |
| high | Yes — must fix |
| medium | No — fix as appropriate; report what's left |
| low | No — advisory only |

`ed3d-plan-and-execute` requires **zero issues including Minor** before proceeding. This plugin deliberately diverges: only critical/high block, medium/low are advisory, the loop caps at `max_rounds` (default 3), and anything unresolved at the cap goes to the operator as an explicit accept/raise/hand-off decision. The rationale: infinite fix loops on advisory findings burn rounds without reducing risk.

## The Guardrail Hook

`hooks/check-review-loop.py` runs on session-stop events and refuses premature stops while the review loop is active:

- Registers under both documented spellings — Copilot-native `agentStop` and the VS Code-compatible `Stop` (which is also Claude Code's stop event). The decision output is stable across fires; if both events fire for one stop, the block counter increments once per event. (Note: `AgentStop` is **not** a documented event name in either runtime — the PascalCase equivalent of `agentStop` is `Stop`.)
- Fail-open everywhere: no state file, malformed JSON, unreadable state, inactive review → exit 0 silently. Hook timeouts fail open per the Copilot hooks reference.
- Blocking emits `{"decision": "block", "reason": "..."}` naming round N of M and the open findings; `round > max_rounds` allows the stop with a reason instructing the agent to surface the operator decision.
- **Owner-scoped review stop:** the parent `agentStop`/`Stop` path compares the event's `sessionId`/`session_id` with the persisted `ownership.session_id`. A different parent session is silently allowed without changing counters or state; missing identity uses the explicit `ownership-recovery-required` allow marker. The guarantee is limited to parent stop/state decisions: the observed `preToolUse` payload has no parent owner field, so the existing review-wide child write enforcement remains in place and is not cross-session isolation.
- **Stale-verdict detection:** when provenance is bound, the hook performs a conservative streaming JSONL scan rather than arbitrary substring or 256 KiB tail scanning. It correlates the dispatch `toolCallId`, reviewer `agentId`, `subagent.started`/`completed`, and the latest reviewer `assistant.message`; `tool.execution_complete` content, prompts, file reads, quoted/fenced/duplicate/trailing/stale/wrong-lineage markers do not qualify. Only the exact nonce-tagged two-line SHIP/FIX-FIRST block with its severity boolean is evidence.
- **Terminal-state enforcement (0.3.1):** a final `SHIP` state only allows a stop when it is consistent — `active: false`, `verdict: "SHIP"`, `consecutive_blocks: 0`. Otherwise the hook blocks, pointing at the adversarial-review skill's terminal-state verification — repeatedly until repaired, bounded by the 7-block safety cap.
- Respects the CLI's 8-consecutive-block cap: after 7 blocks without recorded progress it allows with a warning, so a session can never hard-lock. The loop resets the counter on every round/verdict transition, so it only trips when stops are being blocked with no forward motion.

Run the tests: `python3 plugins/ed3d-orchestrate/hooks/test-check-review-loop.py` and `python3 scripts/test-dispatch-protocol.py` (standalone, zero dependencies).

## The Adversary Write-Guard

`hooks/adversary-write-guard.py` runs on preToolUse (write-class tools) and mechanically enforces the adversary's no-writes rule: while `review.active` is true and `review.verdict` is `PENDING` — the adversary-in-flight window, at every round — write-class tool calls (`edit`, `create`, `apply_patch`, plus legacy Edit/Write variants) from subagent contexts (`call_`-prefixed session ids) are blocked with a diagnostic reason; the reviewer reports findings instead of fixing them. The orchestrator (UUID session id), builders, and the bug-fixer (which runs while verdict is `FIX-FIRST`) are never blocked. If a crashed loop leaves stale active+PENDING state on disk and legitimate subagent writes get blocked, delete or repair `.ed3d/orchestrate-state.json` — the block reason names its path. Known gap: writes via bash redirection are not intercepted; the prose rule remains the backstop there.

Run its tests: `python3 plugins/ed3d-orchestrate/hooks/test-adversary-write-guard.py` (standalone, zero dependencies). The dispatch-protocol suite is `python3 scripts/test-dispatch-protocol.py`.

## Requirements

- GitHub Copilot CLI with plugin + custom agent support
- A local git repository with at least one commit — adversarial review needs a valid `BASE_SHA..HEAD_SHA` range; on a brand-new project the loop initializes git and creates a baseline commit before implementation
- `ed3d-research-agents` (scouts) and `ed3d-plan-and-execute` (builders) installed
- `ed3d-basic-agents` (generic scouts) recommended

## Usage

```
/plugin install ed3d-orchestrate@ed3d-plugins
```

Then, from the repo you want to work on, in a session running on a high-reasoning model:

```
/ed3d-orchestrate:orchestrate add a CLI tool that reverses a string, with tests
```

Watch `.ed3d/orchestrate-state.json` as the loop runs — phase and review transitions are all visible there, and the plan lands in `docs/implementation-plans/`.

### Context handoff and resume

Builders and reviewers run in isolated subagent contexts, but the orchestrating session accumulates every printed subagent response. After the plan-review gate passes, the orchestrator stops at an **operator approval checkpoint** and offers the two approval paths: reply *continue* to approve and proceed in the same context, or `/clear` and then resume to approve and continue with a fresh context — the loop records its full position in the state file (`phase`, `plan_path`, the SHAs, the review block), and completed phases are never repeated. A clean plan-review result does not by itself authorize execution: the approval response (either `continue` or the `/clear` + resume) is processed before any builder dispatch.

A **non-empty task argument always starts a fresh loop** rather than
auto-resuming. It resets every task, plan, approval, SHA, and review field,
including the handoff status, correction attempts, `review.max_rounds`,
history, counters, and nonce; existing plans and commits remain untouched.
An **empty invocation may resume only** a validated state with
`phase: "execute" or "review"`, a non-empty absolute `plan_path` that exists,
and a task that matches the plan context. The clean fresh combination is
`review.active: false` and `review.verdict: "PENDING"` and is not treated as
an in-progress loop. Malformed, partial, legacy, or mismatched state fails
closed.

If read-only planning prevents a reset write, the plan contains this simple
pending handoff record:

```markdown
## Orchestration Handoff
- reset_pending: true
- requested_task: <task text>
- prior_task: <task text or unknown>
- prior_plan_path: <absolute path or none>
- approval: pending
```

It is a **pending record, not authorization**. Once planning ends, the
orchestrator applies the reset, verifies the task and absolute plan path, and
changes `reset_pending: false` in its control-plane handling before approval.
Missing, duplicated, or mismatched records leave execution refused; execution remains refused
until the reset is applied.

Builders and fixers return a Copilot-native **Outcome Handoff** with one row
for every approved `AC.n` or explicitly requested behavior:

```markdown
### Outcome Handoff
- AC.1: complete | incomplete | blocked
  - Changed: file or symbol
  - Evidence: command -> observed result
```

Each row has a `complete, incomplete, or blocked` status, changed location, and behavior-specific command/result;
a green pre-existing suite without that evidence is a suite-only claim, not
completion. The first missing outcome receives one correction attempt through
the existing fixer. A second incomplete/blocked handoff stops before review
and requires a concrete takeover/replan decision.

This boundary is **prompt-only guidance** — enforced by the workflow text, not by **native Copilot runtime enforcement** (unavailable for this boundary: Copilot has no native facet-transition approval primitive here) and not by **repository hook/script enforcement** (deferred until a native builder-dispatch payload and identity are evidenced). The existing `check-review-loop.py` and `adversary-write-guard.py` hooks are unrelated to this approval checkpoint and are unchanged.

State transitions remain explicit. The **transition checklist** requires
persist and re-read each verdict before reporting, history to be
append-only with at most one same-round protocol-failure `PENDING` entry, and
progress to reset `consecutive_blocks`. The hook keeps its atomic
temporary-file replacement, but does not protect concurrent model-mediated state edits.
This remains procedural and protocol-only.

After `/clear`, run `/ed3d-orchestrate:orchestrate` with no arguments — when
the state file is a validated in-progress loop, the command resumes from the
recorded phase, reports where the loop stands, and re-presents any pending
approval checkpoint. The explicit `resume` argument still works, and you can
`/clear` + resume at any other phase boundary on your own initiative; the state
file is current at every transition.

## 0.5.0 — Enforcement Branch B (protocol-only)

The plan-review → builder handoff gate ships as **protocol-only** guidance. This is the **Branch B** decision, recorded in the checked-in evidence artifact [`docs/research/2026-09-03-orchestrate-enforcement-branch-b.evidence.md`](../../docs/research/2026-09-03-orchestrate-enforcement-branch-b.evidence.md).

- **Validation limitation:** on Copilot CLI **1.0.82** the native builder-dispatch payload and agent identity required for a mechanical builder-gate hook could not be validated (no captured builder-dispatch fixture; the hook reference does not specify an agent/resource identity in the pre-tool payload). A mechanical matcher built on that gap would risk blocking legitimate builder dispatches.
- **No builder-gate artifact:** this release adds **no** new `preToolUse` hook script (no `builder-gate.py` or equivalent) to `hooks/`.
- **No builder-gate registration:** the hook manifest is unchanged — only `check-review-loop.py` and `adversary-write-guard.py` remain registered.
- **Not mechanical:** the handoff gate remains **prompt-only guidance**, **not mechanical** and **not** native Copilot runtime enforcement. No mechanical or runtime enforcement claim is made for it. Branch A (a mechanical builder-gate artifact plus registration) is rejected until a native builder-dispatch payload and identity are validated and evidenced.

`python3 scripts/test_orchestrate_enforcement_branch.py` asserts exactly this Branch B contract (zero dependencies, offline).

## Known Limitations

- The plan-review-to-builder handoff approval checkpoint is **prompt-only guidance**: there is no native Copilot runtime enforcement for it, and no repository hook/script backstop (that is deferred until a native builder-dispatch payload and identity are evidenced). An orchestrator could still violate the protocol; no deployment or version-drift limitation is implied by this prompt-only slice beyond that.
- Facet discipline (e.g. read-only planning) is enforced by instruction, not by harness. The guardrail hook narrows this gap only for the review loop.
- The hook's stale-verdict scan requires a nonce and current reviewer lineage; it no longer scans arbitrary tail text. Legacy in-flight state without provenance remains ordinary owner enforcement, a crashed loop can leave stale active+PENDING state that write-blocks subagents until repaired, and bash-redirection writes bypass the write-guard (prose rule remains).
- The state contract distinguishes `same-owner continuation`, `authorized ownership transfer`, and `explicit legacy recovery` through its `ownership` and `review.provenance` blocks. Unavailable completed lineage keeps the valid owner blocked with `review-reconciliation-unavailable`; one existing retry is allowed, then `reconciliation_exhausted` explicitly permits a no-verdict stop with operator choice. No verdict exists in that exhausted state.
- Dispatch model selection is pinned-first best-effort guidance with a conservative explicit-pre-start-rejection-only Auto fallback. The adversary prefers `gpt-6-astra` / `medium`; all other orchestrated roles prefer `gpt-5.6-luna` / `high`. It is not a mechanically intercepted runtime feature; direct agent launches outside this dispatch path inherit account/CLI defaults, while unknown dispatch-error semantics and catalog drift require visible evidence. Preferred-vs-fallback provenance is transcript/report-only and does not survive `/clear` or resume; the existing state schema is not extended to persist it.
- Parallel dispatch can trip provider rate limits; the skills fall back to serial/small-batch dispatch on rate-limit errors.
