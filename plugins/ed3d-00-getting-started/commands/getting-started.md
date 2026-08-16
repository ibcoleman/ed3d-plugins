---
description: Show the ed3d-plugins README and getting started information
---

# Getting Started with ed3d-plugins

Display the content below to the user as formatted Markdown. (Maintainers:
this is a snapshot of the repository README up to, not including, the
Installation section — keep it in sync when the README changes.)

---

# ed3d-plugins

This is my collection of plugins that I use on a day-to-day basis for getting stuff done with Claude Code. Most of these are development-oriented in some way or another, but also often end up being useful for other things. Product design, general research, accidentally becoming my homelab sysadmin—these are a lot of what I've learned so far and what I've found helpful.

The big stick in this repository is `ed3d-plan-and-execute`, which implements an "RPI" (research-plan-implement) loop that I think does a really good job of avoiding hallucination in the planning stages, adhering to high-level product requirements, avoiding drift between design planning and implementation planning, and reviewing the results such that you get out the other end not just what you asked for, but what you actually wanted.

**NOTE:** `ed3d-plugins` is generally a more stable marketplace. If you'd like to track changes as they happen a bit more aggressively, take a look at [`ed3d-plugins-testing`](https://github.com/ed3dai/ed3d-plugins-testing).

## Using `ed3d-plan-and-execute`
More in [the README for the plugin](plugins/ed3d-plan-and-execute/README.md), and it's worth skimming, but here's a quickstart:

```
Rough Idea
    │
    ▼
/start-design-plan  ──────► Design Document (committed to git)
    │
    ▼
/start-implementation-plan ──► Implementation Plan (phase files)
    │
    ▼
/execute-implementation-plan ──► Working Code (reviewed & committed)
```

**Customization:** Create `.ed3d/design-plan-guidance.md` and `.ed3d/implementation-plan-guidance.md` in your project to provide project-specific constraints, terminology, and standards. Run `/how-to-customize` for details.

## Plugins

| Plugin | Description |
|--------|-------------|
| **`ed3d-00-getting-started`** | Getting started guide and onboarding for ed3d-plugins. Run `/getting-started` to see this README. |
| **`ed3d-plan-and-execute`** | Planning and execution workflows for Claude Code. Feed it a decent-sized task and it'll help you get it done in a sustainable and thought-through way |
| **`ed3d-house-style`** | House style for software development; Very Opinionated |
| **`ed3d-basic-agents`** | Core agents for general-purpose tasks (haiku, sonnet, opus). Other plugins expect this to exist |
| **`ed3d-research-agents`** | Agents for research across multiple data sources (codebase, internet, combined); other plugins expect this to exist |
| **`ed3d-extending-claude`** | Knowledge skills for extending Claude Code: plugins, commands, agents, skills, hooks, MCP servers. Other plugins expect this to exist |
| **`ed3d-playwright`**| Playwright automation with subagents |
| **`ed3d-hook-skill-reinforcement`** | UserPromptSubmit hook that reinforces the need to activate skills—helps make sure skills actually get used. Requires `ed3d-extending-claude` to work |
| **`ed3d-hook-claudemd-reminder`** | PostToolUse hook that reminds to update CLAUDE.md before committing |
| **`ed3d-hook-security-hardening`** | PreToolUse and PostToolUse hooks that catch secrets leakage patterns |
| **`ed3d-session-reflection`** | EXPERIMENTAL. Session awareness and conversation review tooling. Requires `ed3d-extending-claude` |
| **`ed3d-orchestrate`** | EXPERIMENTAL. Polytoken-style orchestration loop for Copilot CLI: scout-sweep research, plan-review gate, builder fanout, adversarial review rounds with a stop-guardrail hook. Requires `ed3d-research-agents` + `ed3d-plan-and-execute` |
