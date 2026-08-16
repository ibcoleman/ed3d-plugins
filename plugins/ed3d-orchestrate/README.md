# ed3d-orchestrate

**EXPERIMENTAL. Copilot-first.** A Polytoken-style orchestration loop for GitHub Copilot CLI: scout-sweep research fanout → plan document → plan-review gate → builder fanout → adversarial "tumble dryer" review rounds with a hook-enforced backstop.

This plugin is written for Copilot CLI's native delegation. Its skills use Copilot-native dispatch prose (not Claude Code's XML `Task` blocks), and its agents ship as `*.agent.md`. It installs cleanly under Claude Code too — the guardrail hook fails open when no orchestration state file exists — but the workflow itself targets Copilot sessions.

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

## Agents and Model Bindings

The model map decorrelates builders from reviewers: worker-bee agents run on one family, adversarial/review agents on another, so the reviewer never shares a model family's blind spots with the builder it reviews.

| Agent | Role | Model |
|-------|------|-------|
| `adversary` | Adversarial implementation review, tumble-dryer rounds | `kimi-k3` |
| `plan-reviewer` | Plan-document review gate | `kimi-k3` |

Dispatched from other plugins (this plugin requires them):

| Agent | Plugin | Role | Model |
|-------|--------|------|-------|
| `task-implementor-fast` | ed3d-plan-and-execute | Builder | `gpt-5.6-luna` |
| `task-bug-fixer` | ed3d-plan-and-execute | Review-fix responder | `gpt-5.6-luna` |
| `codebase-investigator` | ed3d-research-agents | Scout: codebase state | `gpt-5.6-luna` |
| `internet-researcher` | ed3d-research-agents | Scout: external knowledge | `gpt-5.6-luna` |
| `combined-researcher` | ed3d-research-agents | Scout: both | `gpt-5.6-luna` |
| `remote-code-researcher` | ed3d-research-agents | Scout: external source code | `gpt-5.6-luna` |
| `haiku-general-purpose` | ed3d-basic-agents | Scout: light legwork | `gpt-5.6-luna` |

Those bindings live in the `*.agent.md` twins shipped alongside each plugin's Claude Code agents.

**Session model:** start orchestration sessions on the same high-reasoning tier as the reviewers (`kimi-k3`). The orchestrator is the main session — there is deliberately no orchestrator agent file.

## Model Overrides

Frontmatter `model` bindings are version-dependent in Copilot CLI — current builds ignore them for plugin agents. The authoritative override is `~/.copilot/settings.json` (user settings; `config.json` is managed automatically) under `subagents.agents`, keyed by bare agent name (unambiguous where the name is unique across installed plugins):

```json
{
  "subagents": {
    "agents": {
      "adversary": { "model": "kimi-k3", "effortLevel": "high" },
      "plan-reviewer": { "model": "kimi-k3", "effortLevel": "high" },
      "task-implementor-fast": { "model": "gpt-5.6-luna" },
      "task-bug-fixer": { "model": "gpt-5.6-luna" }
    }
  }
}
```

**Availability fallback:** when the luna tier is rate-limited (observed in practice), rebind the luna-bound agents to `gemini-3.7-flash` via the same override block. Decorrelation is preserved — reviewers stay on `kimi-k3`.

`gpt-5.3-codex` is a reasonable alternative binding for the builder agents if luna is unavailable and flash is too weak for implementation work.

## State File

The loop maintains `.ed3d/orchestrate-state.json` in the working repository. It is both the audit trail (every transition is inspectable after the fact) and the input the guardrail hook reads.

```json
{
  "task": "add string-reversal CLI with tests",
  "phase": "review",
  "review": {
    "active": true,
    "round": 2,
    "max_rounds": 3,
    "verdict": "FIX-FIRST",
    "open_critical_high": [
      "high: src/cli.py:42 - panics on empty input"
    ],
    "consecutive_blocks": 1
  }
}
```

- `phase`: `research` | `plan` | `execute` | `review`
- `review.verdict`: `PENDING` | `SHIP` | `FIX-FIRST`; final states are `SHIP` (including operator-accepted) or `review.active: false`
- `review.round` goes to `max_rounds + 1` when the circuit-breaker trips — that is the signal the hook uses to allow the stop
- `consecutive_blocks` counts blocks-since-last-progress: the hook increments it, the orchestrating skills reset it to 0 on every round/verdict transition

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
- Respects the CLI's 8-consecutive-block cap: after 7 blocks without recorded progress it allows with a warning, so a session can never hard-lock. The loop resets the counter on every round/verdict transition, so it only trips when stops are being blocked with no forward motion.

Run the tests: `python3 plugins/ed3d-orchestrate/hooks/test-check-review-loop.py` (standalone, zero dependencies).

## Requirements

- GitHub Copilot CLI with plugin + custom agent support
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

## Known Limitations

- Facet discipline (e.g. read-only planning) is enforced by instruction, not by harness. The guardrail hook narrows this gap only for the review loop.
- Frontmatter `model` bindings may be ignored by older Copilot builds — verify with a spot-check of an adversary dispatch, and use the settings.json override if needed.
- Parallel dispatch can trip provider rate limits; the skills fall back to serial/small-batch dispatch on rate-limit errors.
