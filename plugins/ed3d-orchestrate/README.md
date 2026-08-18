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

## Agents and model selection

The Copilot-native `*.agent.md` twins intentionally omit a `model` frontmatter key. Each agent inherits the account's Copilot Auto/default model, so the same plugin works across accounts and model catalogs without stale model IDs or forced tier changes. The twins preserve role descriptions and bodies from their Claude Code originals; they do not prescribe a runtime model.

| Agent group | Role | Model selection |
|-------------|------|-----------------|
| `adversary`, `plan-reviewer` | Review and plan gates | Account Auto/default |
| `task-implementor-fast`, `task-bug-fixer` | Builders and review fixes | Account Auto/default |
| Research agents and `haiku-general-purpose` | Scouts | Account Auto/default |

Dispatched agents come from `ed3d-plan-and-execute`, `ed3d-research-agents`, and `ed3d-basic-agents`; install those plugins when using their roles.

The orchestrator is the main session — there is deliberately no orchestrator agent file. Start it with whatever model and account defaults are appropriate for the task.

## Model and effort defaults

**For marketplace users: no model configuration is required.** Dispatch instructions send no model or effort override; the account's Auto/default and CLI defaults decide both.

You may still configure Copilot's own account or `~/.copilot/settings.json` defaults if you want a preferred model or effort. Such configuration is optional and is applied by Copilot rather than by this plugin. Do not edit the agent twins or dispatch instructions to add model or effort overrides: omission is the compatibility policy.

## State File

The loop maintains `.ed3d/orchestrate-state.json` in the working repository. It is both the audit trail (every transition is inspectable after the fact) and the input the guardrail hook reads.

```json
{
  "task": "add string-reversal CLI with tests",
  "plan_path": "docs/implementation-plans/2026-08-16-string-reverse-cli/plan.md",
  "base_sha": "3f2a1b9",
  "head_sha": "b7ddd28",
  "phase": "review",
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
- **Stale-verdict detection (0.3.3, nonce-gated):** when the stop event carries a transcript path, the hook scans its tail for this loop's nonce-tagged SHIP marker (`VERDICT: SHIP [<nonce>]`, case-normalized). Prose can never contain the nonce-tagged form, so the 0.3.1-era false positives (literal `VERDICT: SHIP` strings from skill/hook text — one of which fabricated a terminal SHIP that overrode the operator) are structurally impossible. State files without a nonce (pre-0.3.3 in-flight loops) skip the scan entirely. Block reasons are diagnostic and addressed to the orchestrator only — never forwarded to subagents, never prescribing concrete state writes.
- **Terminal-state enforcement (0.3.1):** a final `SHIP` state only allows a stop when it is consistent — `active: false`, `verdict: "SHIP"`, `consecutive_blocks: 0`. Otherwise the hook blocks, pointing at the adversarial-review skill's terminal-state verification — repeatedly until repaired, bounded by the 7-block safety cap.
- Respects the CLI's 8-consecutive-block cap: after 7 blocks without recorded progress it allows with a warning, so a session can never hard-lock. The loop resets the counter on every round/verdict transition, so it only trips when stops are being blocked with no forward motion.

Run the tests: `python3 plugins/ed3d-orchestrate/hooks/test-check-review-loop.py` (standalone, zero dependencies).

## The Adversary Write-Guard

`hooks/adversary-write-guard.py` runs on preToolUse (write-class tools) and mechanically enforces the adversary's no-writes rule: while `review.active` is true and `review.verdict` is `PENDING` — the adversary-in-flight window, at every round — write-class tool calls (`edit`, `create`, `apply_patch`, plus legacy Edit/Write variants) from subagent contexts (`call_`-prefixed session ids) are blocked with a diagnostic reason; the reviewer reports findings instead of fixing them. The orchestrator (UUID session id), builders, and the bug-fixer (which runs while verdict is `FIX-FIRST`) are never blocked. If a crashed loop leaves stale active+PENDING state on disk and legitimate subagent writes get blocked, delete or repair `.ed3d/orchestrate-state.json` — the block reason names its path. Known gap: writes via bash redirection are not intercepted; the prose rule remains the backstop there.

Run its tests: `python3 plugins/ed3d-orchestrate/hooks/test-adversary-write-guard.py` (standalone, zero dependencies).

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

Builders and reviewers run in isolated subagent contexts, but the orchestrating session accumulates every printed subagent response. After the plan-review gate passes, the orchestrator **stops and offers the choice**: reply *continue* to proceed in the same context, or `/clear` and then resume to continue with a fresh context — the loop records its full position in the state file (`phase`, `plan_path`, the SHAs, the review block), and completed phases are never repeated.

After `/clear`, run `/ed3d-orchestrate:orchestrate` with no arguments — when a state file exists with an in-progress loop, the command auto-resumes from the recorded phase and reports where the loop stands (0.3.1). The explicit `resume` argument still works, and you can `/clear` + resume at any other phase boundary on your own initiative; the state file is current at every transition.

## Known Limitations

- Facet discipline (e.g. read-only planning) is enforced by instruction, not by harness. The guardrail hook narrows this gap only for the review loop.
- The hook's stale-verdict scan is nonce-gated (0.3.3): it matches only this loop's `VERDICT: SHIP [<nonce>]` marker, so stale verdict strings from a prior loop in the same session can no longer false-match. Residual gaps: pre-0.3.3 in-flight state files carry no nonce and skip the scan; a crashed loop can leave stale active+PENDING state that write-blocks subagents until the state file is repaired; bash-redirection writes bypass the write-guard (prose rule remains).
- Model selection is intentionally inherited from Copilot Auto/default; if you need a preferred model, configure it in Copilot rather than editing the plugin's agent twins or skill dispatch templates.
- Parallel dispatch can trip provider rate limits; the skills fall back to serial/small-batch dispatch on rate-limit errors.
