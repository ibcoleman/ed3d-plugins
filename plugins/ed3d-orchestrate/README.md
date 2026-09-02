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

The Copilot-native `*.agent.md` twins intentionally omit a `model` frontmatter key. Dispatch is pinned-first on best-effort hard-coded IDs, while the twins preserve role descriptions and bodies from their Claude Code originals and remain directly Auto-compatible.

| Agent group | Role | Preferred dispatch |
|-------------|------|--------------------|
| `adversary`, `plan-reviewer` | Review and plan gates | `gpt-5.5` / `xhigh` |
| `task-implementor-fast`, `task-bug-fixer` | Builders and review fixes | `gpt-5.6-luna` / `medium` |
| Research agents and `haiku-general-purpose` | Scouts | `gpt-5.6-luna` / `low` |

On each delegated dispatch, the preferred model/effort is attempted first. Only a visible pre-start rejection explicitly identifying model, account availability, or effort support triggers one fallback with both overrides omitted (Auto); ambiguity and any started dispatch are never retried as model fallback. Direct agent launches remain Auto-compatible.

Dispatched agents come from `ed3d-plan-and-execute`, `ed3d-research-agents`, and `ed3d-basic-agents`; install those plugins when using their roles.

The orchestrator is the main session — there is deliberately no orchestrator agent file. Start it with whatever model and account defaults are appropriate for the task.

## Model and effort defaults

Dispatch uses best-effort hard-coded model IDs and reasoning efforts: reviewers use `kimi-k3` / `high`, builders and fixers use `gpt-5.6-luna` / `medium`, and scouts use `gpt-5.6-luna` / `low`. This is procedural pinned-first guidance, not a mechanically intercepted runtime feature. If Copilot visibly rejects the preferred model, account, or effort before any start signal, retry exactly once with both overrides omitted so Auto-only accounts continue to work; a started or ambiguous outcome is not retried as model fallback. Existing rate-limit and protocol-failure retries remain separate.

No agent frontmatter pins are added, so direct agent launches remain compatible with Auto-only accounts. The observed `claude-haiku-4.5` medium-effort rejection motivates the fallback; Copilot's dispatch-error semantics are otherwise unknown and require visible evidence before any fallback.

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

This boundary is **prompt-only guidance** — enforced by the workflow text, not by **native Copilot runtime enforcement** (unavailable for this boundary: Copilot has no native facet-transition approval primitive here) and not by **repository hook/script enforcement** (deferred until a native builder-dispatch payload and identity are evidenced). The existing `check-review-loop.py` and `adversary-write-guard.py` hooks are unrelated to this approval checkpoint and are unchanged.

After `/clear`, run `/ed3d-orchestrate:orchestrate` with no arguments — when a state file exists with an in-progress loop, the command auto-resumes from the recorded phase and reports where the loop stands (0.3.1). The explicit `resume` argument still works, and you can `/clear` + resume at any other phase boundary on your own initiative; the state file is current at every transition.

## Known Limitations

- The plan-review-to-builder handoff approval checkpoint is **prompt-only guidance**: there is no native Copilot runtime enforcement for it, and no repository hook/script backstop (that is deferred until a native builder-dispatch payload and identity are evidenced). An orchestrator could still violate the protocol; no deployment or version-drift limitation is implied by this prompt-only slice beyond that.
- Facet discipline (e.g. read-only planning) is enforced by instruction, not by harness. The guardrail hook narrows this gap only for the review loop.
- The hook's stale-verdict scan is nonce-gated (0.3.3): it matches only this loop's `VERDICT: SHIP [<nonce>]` marker, so stale verdict strings from a prior loop in the same session can no longer false-match. Residual gaps: pre-0.3.3 in-flight state files carry no nonce and skip the scan; a crashed loop can leave stale active+PENDING state that write-blocks subagents until the state file is repaired; bash-redirection writes bypass the write-guard (prose rule remains).
- Dispatch model selection is pinned-first best-effort guidance with a conservative explicit-pre-start-rejection-only Auto fallback. It is not a mechanically intercepted runtime feature; unknown dispatch-error semantics and catalog drift require visible evidence, and the observed `claude-haiku-4.5` medium-effort rejection remains representative. Preferred-vs-fallback provenance is transcript/report-only and does not survive `/clear` or resume; the existing state schema is not extended to persist it.
- Parallel dispatch can trip provider rate limits; the skills fall back to serial/small-batch dispatch on rate-limit errors.
