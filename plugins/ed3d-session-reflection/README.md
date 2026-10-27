# ed3d-session-reflection

**EXPERIMENTAL.** Session awareness and conversation review tooling for GitHub Copilot CLI, with legacy Claude Code transcript support.

## What It Does

This plugin locates session transcripts and provides tools to review how sessions went — analyzing human prompting effectiveness, agent performance, and environment/tooling gaps.

### Session Awareness

For a current-session review, the skill requires the live `COPILOT_AGENT_SESSION_ID` and checks its identity against the transcript metadata. It uses a runtime-supplied current transcript path when present, otherwise exactly `~/.copilot/session-state/<COPILOT_AGENT_SESSION_ID>/events.jsonl`; it does not scan or choose by recency. An explicit transcript path is historical: it is checked against its canonical session-state directory ID or a required `--session-id`, never against the current session ID. The inline checker reads metadata only and rejects absent, malformed, or conflicting identity.

### Conversation Review

Two skills for reviewing sessions:

- **`/ed3d-session-reflection:review-session`** — Deep qualitative review of the current session (or a specified transcript). Dispatches the conversation reviewer using configured agent preferences. The reviewer reads a private reduced snapshot and writes findings covering what went well, what went wrong, and actionable recommendations.

- **`/review-recent-sessions`** — Reviews the last N sessions (default 5) in the current project. Dispatches parallel Opus reviewers (one per session), then synthesizes cross-session patterns with a Sonnet agent. Identifies recurring issues and highest-impact recommendations.

### Transcript Reduction

A preprocessing script (`reduce-transcript.py`) accepts Copilot CLI `events.jsonl` and legacy Claude Code JSONL transcripts. It removes metadata noise while preserving conversation flow, tool calls, and results. Reduction is not redaction; review artifacts stay local in a fresh private directory and are not publication-ready.

## Requirements

- Before reduction, `copilot plugin list` must confirm `ed3d-session-reflection` and `ed3d-extending-claude` are installed and enabled. The invoking skill loads `ed3d-extending-claude:writing-claude-directives` through the native Skill tool and verifies the reviewer agent and reducer are readable; the reviewer loads that reference skill separately before analysis. Each missing prerequisite stops review with a specific error.

## Installation

```
/plugin install ed3d-session-reflection@ed3d-plugins
```

## Components

| Component | Type | Description |
|-----------|------|-------------|
| `session-start.py` | Hook (SessionStart) | Injects session ID and transcript path into context |
| `reduce-transcript.py` | Script | Strips JSONL to token-efficient text for analysis |
| `conversation-reviewer` | Agent (Opus) | Reads reduced transcript, writes findings to disk |
| `review-session` | Skill | Single-session review orchestration |
| `review-recent-sessions` | Skill | Multi-session parallel review with synthesis |

## How It Works

```
Explicit path / runtime transcript path / current-session canonical path
    │ resolves and verifies one transcript identity
    ▼
/review-session (or /review-recent-sessions)
    │
    ├── reduce-transcript.py  →  token-efficient text
    │
    ├── conversation-reviewer  →  findings.md (per session)
    │
    └── (multi-session only) synthesis agent  →  cross-session patterns
```

These discovery rules apply to `review-session`; the separate
`review-recent-sessions` workflow retains its own discovery instructions.
Editing this repository does not update an installed plugin copy or deploy hooks.

## Review Axes

The reviewer analyzes sessions across three lenses, following the signal rather than forcing equal coverage:

- **Human prompting** — vagueness that caused wrong output, frustration spirals, mid-stream requirement changes, repeated corrections the agent ignored
- **Agent performance** — looping, over-engineering, missed tool usage, partial completion, human rescue patterns
- **Environment gaps** — extensive codebase exploration suggesting missing CLAUDE.md context, repeated manual sequences that should be automated, missing conventions

Recommendations are typed: CLAUDE.md entries (project or user-level), hooks, skills, or general prompting advice.
