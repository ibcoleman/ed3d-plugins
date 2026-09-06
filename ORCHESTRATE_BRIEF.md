# Brief: Pinned Copilot Dispatch with Auto Fallback

## Goal

Restore deliberate model selection for accounts that can select models, while keeping `ed3d-orchestrate` functional on Auto-only/free-tier Copilot accounts.

## Current behavior and evidence

- Copilot-native agent frontmatter remains model-free for Auto compatibility, while orchestrate dispatch prose pins preferred models for model-selectable accounts.
- Direct agent launches outside orchestrate still inherit account/CLI defaults; the repository has no runtime wrapper that can intercept those launches.
- Observed Auto-only failure: `Reasoning effort 'medium' is not supported for model 'claude-haiku-4.5'`.
- Observed delegation failure: `skill(ed3d-plan-and-execute:task-implementor-fast): Skill not found: ed3d-plan-and-execute:task-implementor-fast`; the named resource is an agent (`*.agent.md`), not a skill.
- Auto may provision inexpensive models such as `gpt-5-mini` or `claude-haiku-4.6-mini`; that behavior is acceptable when explicit dispatch is unavailable.

## Desired behavior

1. For a model-selectable account, attempt the role's preferred dispatch parameters:
   - adversary: `gpt-5.6-sol` with medium effort, where supported;
   - plan-reviewer, builders, and fixers: `gpt-5.6-luna` with high effort, where supported;
   - scouts and other roles: `gpt-5.6-luna` with high effort, where supported.
2. If Copilot rejects the dispatch because the account is Auto-only, the model is unavailable, or the effort/model combination is unsupported, retry the same dispatch once with **both** `model` and `reasoning_effort` omitted.
3. The fallback must use the same agent, task prompt, files, and role; only dispatch overrides change.
4. Make fallback visible in the orchestrator's report/state or otherwise unambiguous: distinguish preferred-model success from Auto fallback.
5. Never put model pins back into Copilot-native `*.agent.md` frontmatter. Direct agent launches must remain Auto-compatible and are outside the orchestrate pinning boundary.
6. Keep Claude-native `.md` files unchanged.
7. Preserve the existing state protocol, nonce handling, write-guard, resume behavior, and safety-cap semantics.
8. Every delegated `*.agent.md` resource must be invoked through Copilot's native agent/subagent mechanism, never the Skill loader.

## Scope boundary

This is a focused dispatch-policy change, not a redesign of the orchestration loop. Do not change the review state schema, hook payload handling, verdict protocol, or agent bodies unless research proves the fallback requires a narrowly scoped compatibility adjustment.

## Research questions the orchestrate cycle must answer first

- What exact Copilot CLI tool/request shape represents a subagent dispatch, and how is a provider/account rejection surfaced to the orchestrator?
- Can the skill reliably detect a rejected dispatch and retry, or must fallback be expressed as a procedural instruction to the orchestrator?
- Does a failed dispatch consume the same request/state slot, and can retrying duplicate work create two live subagents?
- Are `model` and `reasoning_effort` independently optional, or must both be omitted together for Auto-only accounts?
- Which preferred model IDs are still valid, and should they be configurable rather than hard-coded?
- How can the workflow record preferred vs fallback execution without making the state protocol brittle?

## Acceptance criteria

- Paid/model-selectable path attempts the preferred model/effort parameters for each role.
- Auto-only path does not terminate on unsupported model/effort errors; it retries once without both overrides and proceeds with the same role/task.
- A supported preferred dispatch is not unnecessarily downgraded to Auto.
- No Copilot-native agent frontmatter contains a model pin.
- No agent name is sent to the Skill loader; validator coverage prevents regression.
- Existing validator and both orchestration hook suites pass.
- A targeted test or deterministic validation covers: preferred success, model rejection fallback, effort rejection fallback, fallback failure, and no duplicate dispatch after a successful preferred call.
- The tumble-dryer adversary reviews both account paths and verifies the error-handling contract against the actual implementation.

## Suggested fresh-context invocation

1. Commit this brief as the baseline with a message such as:
   `docs: add pinned-dispatch fallback implementation brief`
2. Start a fresh Copilot context.
3. Run:
   `/orchestrate Implement ORCHESTRATE_BRIEF.md: pinned Copilot dispatch with Auto fallback. Read the brief first, research the actual Copilot dispatch failure behavior, then execute the full review-gated workflow.`
4. If the current repository already has an active `.ed3d/orchestrate-state.json`, use `/orchestrate resume` only for that existing loop; otherwise start the task above normally.
