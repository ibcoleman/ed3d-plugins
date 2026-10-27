# Brief: Copilot-Configured Dispatch

## Goal

Keep `ed3d-orchestrate` aligned with Copilot's configured subagent settings instead of
maintaining a repository-level model-selection policy.

## Current behavior and evidence

- Copilot-native agent frontmatter is model-free, and orchestrated dispatches leave
  model and effort selection unset so Copilot's configured subagent settings apply.
- Direct agent launches outside orchestrate use the same Copilot account and CLI
  configuration; the repository has no runtime wrapper that can intercept them.
- Every delegated `*.agent.md` resource is an agent, not a skill, and must be
  invoked through Copilot's native agent/subagent mechanism.

## Desired behavior

1. Invoke every delegated role through Copilot's native agent/subagent mechanism.
2. Leave model and effort selection unset on every orchestrated dispatch so
   Copilot's configured subagent settings and account defaults decide them.
3. Preserve the exact role, task prompt, files, and working directory for every
   dispatch.
4. Keep Copilot-native `*.agent.md` frontmatter model-free and leave
   Claude-native `.md` files unchanged.
5. Preserve the existing state protocol, nonce handling, write-guard, resume
   behavior, and safety-cap semantics.

## Scope boundary

This is a focused dispatch-policy change, not a redesign of the orchestration loop. Do not change the review state schema, hook payload handling, verdict protocol, or agent bodies.

## Research questions the orchestrate cycle must answer first

- What configured subagent setting applies to each orchestrated role?
- What exact Copilot CLI tool/request shape represents a native subagent dispatch?
- How does the native dispatch surface provider or account errors to the orchestrator?
- Can deterministic validation confirm that dispatch instructions inherit settings
  rather than introducing repository-level model or effort overrides?

## Acceptance criteria

- Every orchestrated role inherits Copilot's configured subagent settings.
- Dispatch instructions contain no repository-level model or effort overrides.
- No Copilot-native agent frontmatter contains a model pin.
- No agent name is sent to the Skill loader; validator coverage prevents regression.
- Existing validator and both orchestration hook suites pass.
- A targeted test or deterministic validation covers the configured-settings
  dispatch policy and the absence of obsolete model-selection guidance.
- The tumble-dryer adversary reviews the dispatch contract against the actual
  implementation.

## Suggested fresh-context invocation

1. Commit this brief as the baseline with a message such as:
   `docs: document Copilot-configured dispatch`
2. Start a fresh Copilot context.
3. Run:
   `/orchestrate Implement ORCHESTRATE_BRIEF.md: inherit Copilot's configured subagent settings for every dispatch. Read the brief first, verify the current dispatch contract, then execute the full review-gated workflow.`
4. If the current repository already has an active `.ed3d/orchestrate-state.json`, use `/orchestrate resume` only for that existing loop; otherwise start the task above normally.
