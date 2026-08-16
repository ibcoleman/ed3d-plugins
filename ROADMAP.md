# Roadmap

Durable context for humans and agents picking this work up after a break. Each entry says what it is, why it matters, and the concrete next action. Update this file when items land or new ones emerge — it is the project's memory.

Last updated: 2026-08-16

## Next project: subagent session watcher (CLI/TUI)

**Status:** idea validated, not started. **Size:** nights-and-weekends scale.

**Why:** Copilot CLI gives almost no visibility into subagent activity. Polytoken-grade transparency is achievable because Copilot already writes a complete event trace — nobody renders it. A live watcher would show agent cards (model, duration; effort inferred from `subagent.completed` totals), a tool-call ticker, a usage meter, and model-change toasts.

**Empirical groundwork (observed on Copilot CLI 1.0.80, 2026-08-16):**

- Data lives in `~/.copilot/session-state/<uuid>/events.jsonl` (per-session JSONL) and `~/.copilot/logs/` (lifecycle text logs with `SessionAgentExecutor` lines).
- Event types observed, with counts across existing sessions:

| Event | Count | Use |
|---|---|---|
| `subagent.started` / `subagent.completed` | 42 / 38 | Agent lifecycle. `subagent.started` payload keys observed on 1.0.80: `agentName`, `agentDisplayName`, `agentDescription`, `model`, `toolCallId` — no `reasoning_effort`, no `mode`. Effort is not observable in the event stream; infer it from `subagent.completed` (`totalTokens`, `totalToolCalls`, `durationMs`) |
| `tool.execution_start` / `tool.execution_complete` | 882 / 880 | Per-tool-call timing |
| `assistant.turn_start`/`end`, `assistant.message` | 254/247, 679 | Turn structure and output |
| `session.model_change` | 29 | Live model switches |
| `session.usage_checkpoint` | 30 | AIC/token usage |
| `skill.invoked` | 118 | Skill activation feed |
| `permission.requested`/`completed`, `hook.start`/`end` | 85, 1583 | Permission prompts and hook firings |

**Spike questions to answer first:**

1. Is `events.jsonl` written truly live or batched at turn end? (Determines `tail -f` viability vs polling.)
2. Do subagent tool calls land in the parent session's stream, or do subagents get their own session dirs? (Determines whether per-agent drill-down is free.)
3. Schema drift across CLI versions — the parser needs tolerant parsing (jq-style fallbacks) and findings pinned per version; 1.0.80 already changed config behavior under us once.

**Staging:**

1. `tail -f | jq` filter — an evening of work, immediately useful.
2. Single-file TUI (Rust, or Python + textual).
3. Optionally ship as an ed3d plugin alongside `ed3d-session-reflection` (live watching vs. its post-hoc analysis).

## Findings: ed3d-orchestrate review-loop forensic pass (2026-08-16)

Forensic pass over 6 Copilot sessions (7 adversary dispatches, 2026-08-15/16):

- **Verdict write-back bug, observed 3×** (sessions `147aa7cc`, `39d73ac6`, `d7b09180`): the orchestrator parsed `VERDICT: SHIP` but never wrote it back to `.ed3d/orchestrate-state.json`, so the `agentStop` guardrail blocked legitimate stops (`consecutive_blocks` reached 4 in one run) and block-spam leaked into adversary context. Fix landed in ed3d-orchestrate 0.3.0 (commit-before-print ordering, the atomicity rule, resume reconciliation).
- **Rounds split across sessions by design** — `/clear`+resume can land mid-loop, so per-session dispatch counts undercount a loop. Count rounds via `review.history` in the state file, not dispatch counts.
- **Adversary effort is healthy**: 13–27 tool calls and 280K–825K tokens per review, with live repro of findings. One-round SHIP verdicts were protocol-correct; the defect was orchestrator-side, not reviewer laziness.
- One pre-0.1.1 run dispatched the adversary on a `gpt-5.4-mini` fallback (unpinned dispatch models) — the 0.1.1 pinning closed this.

## Findings: 0.3.0 live validation (2026-08-16)

First real-world run of 0.3.0 on a toy Rust task (`~/Projects/toyapp`, one `/clear`+resume split) against Copilot CLI 1.0.80:

- **Verdict write-back partially fixed:** the final state did record `verdict: "SHIP"`, `active: false`, and a correct round-1 `review.history` entry — but only after the fact. The orchestrator let the stop hook fire repeatedly while state was still `PENDING` (`consecutive_blocks` reached 7, tripping the never-lock allowance), and the final state edit left `consecutive_blocks: 7` instead of resetting it. Prose alone did not make the commit happen before the first post-verdict stop.
- **The adversary respected the no-writes rule** — the successful state-file edit came from the parent orchestrator, and the adversary's own report correctly diagnosed the state-recording failure rather than "fixing" it.
- **Git baseline gap:** with no instruction to create a repo, the implementor skipped `git init` entirely (run 1 failed review — no SHAs); when told to init, it made only the implementation commit, leaving no committed baseline and no `BASE_SHA`. Adversarial review needs a real commit range.
- **Bare-command resume stumble:** `/ed3d-orchestrate:orchestrate` with no args after `/clear` asked "what task?" even with a resumable state file on disk; the model recovered when told to "continue the current loop", but the command should resume on its own.
- **Scout naming confusion is cosmetic:** the UI label `haiku-general-purpose` is the agent ID, not the runtime model — session metrics showed luna doing the work; the agent names are legacy Claude-era tier names.
- Fixes landed in 0.3.1: hook now scans the stop event's transcript tail for a rendered SHIP verdict and blocks with commit instructions (cap-bounded like every block); terminal SHIP states must be consistent (`active: false`, `consecutive_blocks: 0`) or the stop blocks for state repair (also cap-bounded); command auto-resumes when the state file records an in-progress loop; git baseline (`git init` + initial commit + `base_sha`/`head_sha` recording) is a mandatory preflight.

## Deferred follow-ups (ed3d-orchestrate)

- **Hard-enforced context gate.** A `preToolUse` hook variant that blocks the first builder dispatch while a `gate_pending` flag is set in `.ed3d/orchestrate-state.json`. Build only if the prose gate (0.2.1) proves skippable in practice. Next action: watch one real run; if the gate gets blown through, build this.
- **Upstream PR to `ed3dai/ed3d-plugins`.** Agent twins + `ed3d-orchestrate`. PR text lives at `~/Projects/project-orpheus/copilot-fixes/PR_DESCRIPTION.md` but covers through 0.1.0 only. Next action: refresh it (pinned dispatch models 0.1.1, handoff/resume 0.2.0, mandatory gate 0.2.1, review-loop hardening 0.3.0/0.3.1) before opening.
- **Model-id verification.** `kimi-k3`, `gpt-5.6-luna`, `gemini-3.5-flash` are pinned in the three orchestrate skill templates. All three confirmed live on 1.0.80 after 0.1.1 (reviewers on K3, workers on Luna/Gemini). Re-verify after Copilot CLI updates; model catalogs drift.
- **`settings.json` subagents schema discrepancy.** The Copilot config-dir reference documents `subagents.agents.<name>` (`model`/`effortLevel`/`contextTier`), but hand-edits on 1.0.80 produced fallback models and an unexpected `minimal` effort (dispatch-time params won). Prefer the `/subagents` picker. Next action: consider filing an upstream issue against `github/copilot-cli` with the evidence from the 2026-08-16 session.
- **Seeded-defect canary.** The 2026-08-16 forensic pass ruled out reviewer laziness but not misses. Inject 2–3 known-subtle bugs into a shipped commit range and dispatch the adversary blind, as a positive control on detection sensitivity. Next action: pick a shipped range, seed the bugs on a scratch branch, run one adversary dispatch, compare its findings against the seeded list.
- **Per-loop nonce in the verdict block.** The 0.3.1 hook's transcript-tail verdict scan can false-positive when one long session starts a second orchestrate task after a SHIPed first one (stale verdict string still in the tail); obeying the misplaced instruction would fabricate a terminal SHIP for the new task. Precise fix: generate a nonce per review loop, include it in the adversary dispatch prompt, and require it echoed inside the verdict block; the hook scans for the nonce instead of bare verdict strings. Costs a small cross-plugin protocol change (adversary agent + skill + hook). Next action: design the nonce format if the false positive is ever observed live.
- **Polytoken ↔ ed3d-plugins prompt cross-pollination** (parked by operator 2026-08-16). Compare internal Polytoken prompt bodies (the adversarial-review skill; the adversary/builder/scout/plan-reviewer subagent definitions) against ed3d-plugins agent prompts — both the new Copilot-native twins (`adversary.agent.md`, `plan-reviewer.agent.md`) and the legacy upstream-derived ones (`task-implementor-fast`, `code-reviewer`, the research agents). Catalogue transferable robustness patterns (rationalization tables, output contracts, verification-first requirements, atomic state rules, severity ladders) and pilot the winners on `adversary` and `code-reviewer`. Next action: side-by-side read of both prompt families, one-page findings note.
