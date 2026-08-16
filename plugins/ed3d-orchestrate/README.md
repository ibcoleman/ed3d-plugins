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

**For marketplace users: no additional configuration is required.** The skills pin `model` and `reasoning_effort` on every dispatch, so installing the plugin (plus `ed3d-research-agents` and `ed3d-plan-and-execute`) is enough — the bindings below matter only if you want to change them, or if your model catalog spells the ids differently (edit the pinned ids in the three skill templates).

There are three binding layers; they do not behave symmetrically on current builds (verified on Copilot CLI 1.0.80):

1. **Per-dispatch parameters (operative layer).** Copilot's subagent dispatch accepts `model` and `reasoning_effort` arguments on each dispatch, and these take precedence over everything else. The orchestrating model will pick values on its own if the skill doesn't pin them — including unsupported combinations (e.g. `gpt-5.4` + `reasoning_effort: minimal`) that fail the dispatch. This plugin's skills therefore pin them explicitly on every dispatch: reviewers `kimi-k3`/`high`, builders and scouts `gpt-5.6-luna`/`low`-`medium`, with `gemini-3.5-flash` as the documented availability fallback for luna-bound agents.
2. **`~/.copilot/settings.json` → `subagents.agents.<name>`** (per the Copilot config-dir reference: `model`/`effortLevel`/`contextTier`). Documented, but hand-edits have produced fallback-to-default behavior on 1.0.80 — prefer the `/subagents` picker, which persists this config in the schema the CLI actually reads.
3. **Agent frontmatter `model`** — version-dependent and, on 1.0.80 with pinned dispatch params, overridden. The twins carry it as declarative documentation of the intended binding.

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

**Availability fallback:** when the luna tier is rate-limited (observed in practice), rebind the luna-bound agents to `gemini-3.5-flash` — either via the dispatch parameters (skills) or the settings block above. Decorrelation is preserved — reviewers stay on `kimi-k3`.

`gpt-5.3-codex` is a reasonable alternative binding for the builder agents if luna is unavailable and flash is too weak for implementation work.

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
    ]
  }
}
```

- `phase`: `research` | `plan` | `execute` | `review`
- `base_sha` / `head_sha`: the commit range under review — recorded before builders run and after they commit; adversarial review refuses to start without both valid
- `review.verdict`: `PENDING` | `SHIP` | `FIX-FIRST`; final states are `SHIP` (including operator-accepted) or `review.active: false`
- `review.round` goes to `max_rounds + 1` when the circuit-breaker trips — that is the signal the hook uses to allow the stop
- `review.history`: append-only per-round verdict record; survives `/clear`+resume; ignored by the hook
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
- **Stale-verdict detection (0.3.1):** when the stop event carries a transcript path, the hook scans its tail; if the adversary already rendered `VERDICT: SHIP` + `has_critical_or_high: false` while the state file still says `PENDING`/active, the block reason instructs the orchestrator to commit the verdict (including `consecutive_blocks: 0`) instead of re-dispatching. Like every block it counts toward the 7-block safety cap, which takes precedence over it.
- **Terminal-state enforcement (0.3.1):** a final `SHIP` state only allows a stop when it is consistent — `active: false`, `verdict: "SHIP"`, `consecutive_blocks: 0`. Otherwise the hook blocks with instructions to repair the state file before reporting — repeatedly until repaired, bounded by the 7-block safety cap.
- Respects the CLI's 8-consecutive-block cap: after 7 blocks without recorded progress it allows with a warning, so a session can never hard-lock. The loop resets the counter on every round/verdict transition, so it only trips when stops are being blocked with no forward motion.

Run the tests: `python3 plugins/ed3d-orchestrate/hooks/test-check-review-loop.py` (standalone, zero dependencies).

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
- The hook's stale-verdict scan is a heuristic: it searches the transcript tail for the adversary's verdict strings. In a very long single session that starts a second orchestrate task after a SHIPed first one, a stale verdict match can block with a misplaced commit instruction; the 7-block cap bounds the loop, but obeying the instruction on a stale match would write a terminal SHIP into the new task's fresh review state, silently skipping its review. `/clear` between tasks avoids it entirely; the precise fix — a per-loop nonce echoed in the adversary's verdict block — is deferred (see ROADMAP).
- Frontmatter `model` bindings may be ignored by older Copilot builds — verify with a spot-check of an adversary dispatch, and use the settings.json override if needed.
- Parallel dispatch can trip provider rate limits; the skills fall back to serial/small-batch dispatch on rate-limit errors.
- Per-dispatch model selection is the operative binding layer on current builds; if the skills' pinned model ids drift from your catalog (`kimi-k3`, `gpt-5.6-luna`, `gemini-3.5-flash`), correct the ids in the skill dispatch templates or via `/subagents`.
