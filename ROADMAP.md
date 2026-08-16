# Roadmap

Durable context for humans and agents picking this work up after a break. Each entry says what it is, why it matters, and the concrete next action. Update this file when items land or new ones emerge — it is the project's memory.

Last updated: 2026-08-16

## Next project: subagent session watcher (CLI/TUI)

**Status:** idea validated, not started. **Size:** nights-and-weekends scale.

**Why:** Copilot CLI gives almost no visibility into subagent activity. Polytoken-grade transparency is achievable because Copilot already writes a complete event trace — nobody renders it. A live watcher would show agent cards (model, reasoning effort, mode, duration), a tool-call ticker, a usage meter, and model-change toasts.

**Empirical groundwork (observed on Copilot CLI 1.0.80, 2026-08-16):**

- Data lives in `~/.copilot/session-state/<uuid>/events.jsonl` (per-session JSONL) and `~/.copilot/logs/` (lifecycle text logs with `SessionAgentExecutor` lines).
- Event types observed, with counts across existing sessions:

| Event | Count | Use |
|---|---|---|
| `subagent.started` / `subagent.completed` | 42 / 38 | Agent lifecycle; payload carries `agent_type`, name, `model`, `reasoning_effort`, `mode` (sync/background) |
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

## Deferred follow-ups (ed3d-orchestrate)

- **Hard-enforced context gate.** A `preToolUse` hook variant that blocks the first builder dispatch while a `gate_pending` flag is set in `.ed3d/orchestrate-state.json`. Build only if the prose gate (0.2.1) proves skippable in practice. Next action: watch one real run; if the gate gets blown through, build this.
- **Upstream PR to `ed3dai/ed3d-plugins`.** Agent twins + `ed3d-orchestrate`. PR text lives at `~/Projects/project-orpheus/copilot-fixes/PR_DESCRIPTION.md` but covers through 0.1.0 only. Next action: refresh it (pinned dispatch models 0.1.1, handoff/resume 0.2.0, mandatory gate 0.2.1) before opening.
- **Model-id verification.** `kimi-k3`, `gpt-5.6-luna`, `gemini-3.5-flash` are pinned in the three orchestrate skill templates. All three confirmed live on 1.0.80 after 0.1.1 (reviewers on K3, workers on Luna/Gemini). Re-verify after Copilot CLI updates; model catalogs drift.
- **`settings.json` subagents schema discrepancy.** The Copilot config-dir reference documents `subagents.agents.<name>` (`model`/`effortLevel`/`contextTier`), but hand-edits on 1.0.80 produced fallback models and an unexpected `minimal` effort (dispatch-time params won). Prefer the `/subagents` picker. Next action: consider filing an upstream issue against `github/copilot-cli` with the evidence from the 2026-08-16 session.
