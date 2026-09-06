# ed3d-plugins

This is ed3d's development toolkit — plugins and packages I use day-to-day for getting stuff done, now targeting GitHub Copilot CLI (since 2026-08-31). Most of these are development-oriented in some way or another, but also often end up being useful for other things. Product design, general research, accidentally becoming my homelab sysadmin—these are a lot of what I've learned so far and what I've found helpful. Claude Code artifacts remain published as frozen legacy; new work is Copilot-first/Copilot-only.

> **Repository status: Copilot-targeted.** As of 2026-08-31 this repository targets GitHub Copilot CLI. New packages and all new development target Copilot CLI; Claude Code is no longer developed against, and its existing plugins are frozen legacy. Copilot CLI reads [`AGENTS.md`](AGENTS.md) as its primary instructions, and the current project's plan and deferred follow-ups live in [`ROADMAP.md`](ROADMAP.md).

The big stick in this repository is `ed3d-plan-and-execute`, which implements an "RPI" (research-plan-implement) loop that I think does a really good job of avoiding hallucination in the planning stages, adhering to high-level product requirements, avoiding drift between design planning and implementation planning, and reviewing the results such that you get out the other end not just what you asked for, but what you actually wanted.

**NOTE:** `ed3d-plugins` is generally a more stable marketplace. If you'd like to track changes as they happen a bit more aggressively, take a look at [`ed3d-plugins-testing`](https://github.com/ed3dai/ed3d-plugins-testing).

## Using `ed3d-plan-and-execute`
More in [the README for the plugin](plugins/ed3d-plan-and-execute/README.md), and it's worth skimming, but here's a quickstart:

> **Frozen legacy:** the user-facing planning commands below (`/start-design-plan`, `/start-implementation-plan`, `/execute-implementation-plan`, `/flesh-it-out`, `/how-to-customize`) are deprecated/frozen — new orchestration targets `ed3d-orchestrate`. This plugin's builder/fixer agents remain a live dependency of `ed3d-orchestrate` and stay maintained.

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
| **`ed3d-plan-and-execute`** | FROZEN LEGACY. Planning and execution workflows for Claude Code — user-facing planning commands deprecated/frozen; its builder/fixer agents remain a live dependency of `ed3d-orchestrate` |
| **`ed3d-house-style`** | House style for software development; Very Opinionated |
| **`ed3d-basic-agents`** | Core agents for general-purpose tasks (haiku, sonnet, opus). Other plugins expect this to exist |
| **`ed3d-research-agents`** | Agents for research across multiple data sources (codebase, internet, combined); other plugins expect this to exist |
| **`ed3d-extending-claude`** | Knowledge skills for extending Claude Code: plugins, commands, agents, skills, hooks, MCP servers. Other plugins expect this to exist |
| **`ed3d-playwright`**| Playwright automation with subagents |
| **`ed3d-hook-skill-reinforcement`** | UserPromptSubmit hook that reinforces the need to activate skills—helps make sure skills actually get used. Requires `ed3d-extending-claude` to work |
| **`ed3d-hook-claudemd-reminder`** | PostToolUse hook that reminds to update CLAUDE.md before committing |
| **`ed3d-hook-security-hardening`** | PreToolUse and PostToolUse hooks that catch secrets leakage patterns |
| **`ed3d-hook-jj-git-safety`** | Copilot-only. GitHub Copilot CLI-only preToolUse hook and Agent Skill that protect jj + Git repositories from unsafe mutations and jj metadata pollution; POSIX/WSL only |
| **`ed3d-completion-summary`** | Copilot CLI-only. sessionStart reminder hook + work-completion-summary Agent Skill for end-of-work executive handoffs. Inactive by default; explicit deployment required |
| **`ed3d-session-reflection`** | EXPERIMENTAL. Session awareness and conversation review tooling. Requires `ed3d-extending-claude` |
| **`ed3d-orchestrate`** | EXPERIMENTAL. Polytoken-style orchestration loop for Copilot CLI: scout-sweep research, plan-review gate, builder fanout, adversarial review rounds with a stop-guardrail hook. 0.5.0 handoff gate is protocol-only (Branch B). Requires `ed3d-research-agents` + `ed3d-plan-and-execute` |

## Installation

### Add the marketplace
```bash
/plugin marketplace add https://github.com/ed3dai/ed3d-plugins.git
```

### Install Claude Code plugins (legacy, frozen)
The historical Claude Code plugins are available from the `ed3d-plugins` marketplace, but are frozen legacy — no new Claude Code development happens here:
```bash
/plugin install ed3d-plan-and-execute@ed3d-plugins
/plugin install ed3d-house-style@ed3d-plugins
# ... etc
```

`ed3d-hook-jj-git-safety` is a Copilot CLI-only package and is not installed through Claude Code. Follow its plugin README for explicit Copilot hook and skill deployment. `ed3d-completion-summary` follows the same model — see its plugin README for explicit Copilot hook and skill install paths.

## Repository Structure

```
ed3d-plugins/
├── .claude-plugin/
│   └── marketplace.json
├── plugins/
│   ├── ed3d-00-getting-started/
│   ├── ed3d-plan-and-execute/
│   ├── ed3d-house-style/
│   ├── ed3d-basic-agents/
│   ├── ed3d-research-agents/
│   ├── ed3d-extending-claude/
│   ├── ed3d-playwright/
│   ├── ed3d-hook-skill-reinforcement/
│   ├── ed3d-hook-claudemd-reminder/
│   ├── ed3d-hook-security-hardening/
│   ├── ed3d-hook-jj-git-safety/
│   ├── ed3d-completion-summary/
│   ├── ed3d-session-reflection/
│   └── ed3d-orchestrate/
└── README.md
```

## Copilot CLI compatibility

This repository is Copilot-targeted. Copilot CLI reads the repo-root [`AGENTS.md`](AGENTS.md) as its primary instructions, so those are the canonical agent instructions and conventions. The plugins and packages here load under GitHub Copilot CLI:

- Every role agent ships a Copilot-native `<name>.agent.md` twin beside its Claude Code `<name>.md` definition — same body and strict-quoted frontmatter. Twins are model-free; model-family separation is applied at dispatch time via pinned-first attempts with Auto fallback. The Claude Code files are untouched.
- `ed3d-orchestrate` is a Copilot-first plugin implementing the full orchestration loop (scout sweep → plan → plan review → builders → adversarial review rounds) with an `agentStop` guardrail hook. It installs under Claude Code too, but its workflow targets Copilot sessions. Model bindings are pinned by the plugin's skills on every dispatch — no extra configuration required.
- `ed3d-hook-jj-git-safety` is a Copilot CLI-only package. It is cataloged here for distribution and versioning, but it is not a Claude Code plugin; deploy its hook and skill using the package README's Copilot instructions.

Run `python3 scripts/validate_plugins.py` (stdlib-only, zero dependencies) to check twin frontmatter, model bindings, dispatch-protocol rules, and marketplace integrity. Run `python3 scripts/test-dispatch-protocol.py` alongside the orchestrate hook suites for focused dispatch-protocol coverage.

## Migration & release notes

### ed3d-orchestrate 0.5.0 — Enforcement Branch B (protocol-only) — 2026-09-03

The plan-review → builder handoff gate ships as **protocol-only** (Branch B). The checked-in evidence artifact [`docs/research/2026-09-03-orchestrate-enforcement-branch-b.evidence.md`](docs/research/2026-09-03-orchestrate-enforcement-branch-b.evidence.md) documents the **Copilot CLI 1.0.82 validation limitation** (no native builder-dispatch payload/identity validated, so a mechanical builder-gate hook cannot be built safely) and the protocol-only status: **no builder-gate hook artifact**, **no builder-gate hook registration**, and **no mechanical claims**. `python3 scripts/test_orchestrate_enforcement_branch.py` asserts exactly this Branch B contract. Branch A (a mechanical builder-gate artifact + registration) remains rejected until a native builder-dispatch payload and identity are validated and evidenced.

In the same release, `ed3d-plan-and-execute`'s user-facing planning commands are labeled deprecated/frozen; its builder/fixer agents remain a live dependency of `ed3d-orchestrate`.

## Roadmap

Deferred follow-ups and the next project — a subagent session watcher that renders Copilot's event stream live — live in [ROADMAP.md](ROADMAP.md). Consult it before planning new work here.

## Contributing
Issues and pull requests gratefully solicited, except `ed3d-house-style` is _my_ house style, and provided for reference, so I might not take contributions there. (You can make your own house-style plugin though and use that instead!)

## Attribution

`ed3d-plan-and-execute` and parts of `ed3d-extending-claude` are derived from [`obra/superpowers`](https://github.com/obra/superpowers) by Jesse Vincent. The original plugin has been folded, spindled, and mutilated extensively.

Some skills in `ed3d-house-style` are derived from `obra/superpowers` and others (`property-based-testing` is a big one) are derived from the [Trail of Bits Skills repository](https://github.com/trailofbits/skills).

## License

The original [obra/superpowers](https://github.com/obra/superpowers) code in this repository is licensed under the MIT License, copyright Jesse Vincent. See `plugins/ed3d-plan-and-execute/LICENSE.superpowers`.

All other content is licensed under the [Creative Commons Attribution-ShareAlike 4.0 International License](http://creativecommons.org/licenses/by-sa/4.0/).