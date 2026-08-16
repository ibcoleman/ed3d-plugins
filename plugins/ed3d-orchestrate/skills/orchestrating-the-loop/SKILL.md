---
name: "orchestrating-the-loop"
description: "Master workflow for the ed3d-orchestrate loop: scout-sweep research, read-only plan document, plan-reviewer gate, builder fanout, adversarial tumble-dryer review rounds, final assembled report. Maintains .ed3d/orchestrate-state.json throughout so the guardrail hook can enforce the review loop."
user-invocable: true
---

# Orchestrating the Loop

The full orchestration loop, Polytoken-style: research → plan → plan-review gate → execute → adversarial review rounds → report. You are the orchestrator (the main session); you dispatch specialist agents and never do their work yourself when a specialist exists.

**Do not use nested subagents.** You dispatch first-level scouts, reviewers, builders, and fixers. Every dispatched agent must return directly to you. Include the line "Do not dispatch or invoke any subagents" in every dispatch prompt — do not rely on the agents remembering it.

## State Protocol (mandatory)

At loop start, create `.ed3d/orchestrate-state.json` in the working directory of the repo you are operating on:

```json
{
  "task": "one-line description of the task",
  "phase": "research",
  "review": {
    "active": false,
    "round": 0,
    "max_rounds": 3,
    "verdict": "PENDING",
    "open_critical_high": [],
    "consecutive_blocks": 0
  }
}
```

- Update `phase` at every phase transition: `research` → `plan` → `execute` → `review`.
- The `adversarial-review` skill owns the review block during the dryer; when it activates the loop it sets `review.active: true`, `round: 1`.
- Handle `consecutive_blocks` correctly in every rewrite: the guardrail hook (`check-review-loop.py`) increments it each time it blocks a stop; reset it to 0 whenever the loop makes progress (round advanced, verdict changed, or findings changed). Dropping the key weakens the hook's stop protection.
- On completion (SHIP or operator-accepted), set `review.active: false` and leave the final `verdict` in place. The state file is the audit trail — the operator can reconstruct every transition from it after the fact.

## Phase 1: Research

Engage the `scout-sweep` skill (ed3d-orchestrate). Choose 2–4 focus areas, dispatch the researcher agents, synthesize, then read the critical paths yourself.

**You write the plan; your claims must be first-hand.** Scout summaries are inputs, not substitutes for reading the code.

Update state: `phase: "plan"` when research synthesis is done.

## Phase 2: Plan

Write the plan document to:

```
docs/implementation-plans/<YYYY-MM-DD>-<slug>/plan.md
```

Required sections, in order:

1. **Goal** — what is being built and why
2. **Implementation Summary** — condensed overview of the approach
3. **Implementation Plan** — phased, concrete work breakdown with file targets
4. **Acceptance Criteria** — numbered `AC.n`, each independently verifiable
5. **Test Strategy** — how each AC is verified, with named tests or commands
6. **Review Strategy** — how the work will be reviewed
7. **Risks** — blockers, open decisions, unknowns with decision procedures

Every AC must be verifiable by a named test or command. Every cited file path must exist — you verified them in Phase 1.

**Planning is read-only.** The plan document itself is the only thing you write in this phase. No code changes, no config changes, no scaffolding, no "quick wins". If the research surfaced a trivially-fixable problem, it goes in the plan, not in the working tree.

## Phase 3: Plan-Review Gate

The plan does not proceed to execution until it survives review.

1. Dispatch `plan-reviewer` (ed3d-orchestrate) with `model: kimi-k3`, `reasoning_effort: high`, passing `PLAN_PATH` (absolute) and `REPO_ROOT` (absolute). **Print its full response.**
2. Parse the verdict (`VERDICT: SHIP` / `VERDICT: FIX-FIRST`, `has_critical_or_high`).
3. On critical/high findings: fix the plan document, then re-dispatch `plan-reviewer` **once**.
4. If critical/high findings persist after the single re-review: **stop and present them to the operator.** The operator decides whether to revise again, proceed with acknowledged risks, or abandon. Do not proceed to execution on your own authority with open critical/high plan findings.

## Phase 4: Execute

Fan out builders. One bounded task per dispatch — a builder gets a task it can complete fully with tests and a commit.

- Dispatch `task-implementor-fast` (ed3d-plan-and-execute) for implementation tasks, pinning the dispatch parameters: `model: gpt-5.6-luna`, `reasoning_effort: medium` (fall back to `gemini-3.5-flash` on luna rate limits).
- **Copilot's dispatch tool accepts per-dispatch `model` and `reasoning_effort`, and these override agent frontmatter and `/subagents` defaults.** Without explicit pins, the orchestrating model picks models on its own — including unsupported combinations (e.g. `gpt-5.4` with `reasoning_effort: minimal`), which fail the dispatch. Pin them on every dispatch: reviewers get `kimi-k3`/`high`, builders and scouts get `gpt-5.6-luna`/`low`-`medium`.
- **Independent tasks may run in parallel; dependent tasks must be sequenced.** If a dispatch fails with a provider rate-limit error, serialize: at most 2 in flight for the rest of the phase.
- Each dispatch prompt includes: the plan path (absolute), the task number, the working directory, and "Do not dispatch or invoke any subagents."

**Transparency rules (inherited from executing-an-implementation-plan):**

- The human cannot see what subagents return. You are their window into the work.
- After EVERY subagent completes, print its **full response** before taking any other action. No summarizing, no paraphrasing. Include test counts, issue lists, commit hashes, error messages.
- Before every dispatch, say in 2–3 sentences what you're asking the agent to do and which phase it covers.

Update state: `phase: "execute"` before the first builder dispatch; `phase: "review"` when all builders have reported.

## Phase 5: Tumble Dryer

Engage the `adversarial-review` skill (ed3d-orchestrate). It runs the review loop: adversary dispatch → verdict → fix critical/high → re-review, until SHIP or the round cap, then the operator circuit-breaker. The guardrail hook will block premature session stops while `review.active` is true — that is by design; finish the loop or circuit-break properly rather than fighting the hook.

## Phase 6: Assemble and Report

Final report to the operator:

- **Per phase**: what was dispatched, what came back (builder summaries with commit refs; review rounds with verdicts)
- **Review outcome**: rounds run, findings by severity, what was fixed, what remains advisory-only (medium/low left unfixed, listed explicitly)
- **Compromises**: any (there should be none; if there are — e.g. "couldn't run integration tests, continued anyway" — call them out as partial failures and say what the operator must do now)
- **Final verdict** and the state file as the audit trail
- **Next steps**

## Common Rationalizations — STOP

| Excuse | Reality |
|--------|---------|
| "I know this codebase; skip the scout sweep" | No. Research-first is the loop's foundation. At minimum one codebase scout. |
| "The plan is clear in my head; I'll write it as I go" | No. The plan document is the contract builders and reviewers work against. |
| "Plan-reviewer only found medium issues; skip the re-review" | Medium/low don't require fixes. Critical/high do — fix, re-review once, then operator decides. |
| "I'll summarize the builder's response for the user" | No. Print the full response. Always. |
| "The adversary didn't mention the prior issue, so it's fixed" | No. Silence is not confirmation. Carry it forward until explicitly confirmed fixed. |
| "Medium/low findings — I'll fix them all anyway to be safe" | Your call, but not required — this loop ships with advisory findings listed. Don't burn rounds on them. |
| "The stop hook keeps blocking; I'll just keep stopping" | The hook blocks while the review loop is active. Finish the loop (SHIP) or circuit-break (round > max_rounds, operator decides). |
| "I'll dispatch a builder from a builder" | No. No nested subagents. Ever. You dispatch; they work and return. |
