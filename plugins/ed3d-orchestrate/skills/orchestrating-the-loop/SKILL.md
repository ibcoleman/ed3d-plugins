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
  "plan_path": null,
  "base_sha": null,
  "head_sha": null,
  "phase": "research",
  "review": {
    "active": false,
    "round": 0,
    "max_rounds": 3,
    "verdict": "PENDING",
    "open_critical_high": [],
    "consecutive_blocks": 0,
    "history": [],
    "nonce": null
  }
}
```

The review block's `history` field is the append-only round record:

```json
"history": [
  {"round": 1, "verdict": "FIX-FIRST", "critical_high": 1, "advisory": 6},
  {"round": 2, "verdict": "SHIP", "critical_high": 0, "advisory": 0}
]
```

- Before Phase 1, verify the git baseline: the working directory must be inside a local git repository with at least one commit. If no git repo exists and the directory is empty or the task is to create a new project, run `git init`, create a minimal initial commit, and record its SHA as `base_sha`. If no git repo exists in a non-empty directory, ask before initializing. If a git repo exists but has no commits, create an initial commit before implementation. Do not enter Phase 4 without a valid `base_sha`.
- Update `phase` at every phase transition: `research` → `plan` → `execute` → `review`.
- Record `base_sha` immediately before dispatching builders in Phase 4, and record `head_sha` immediately after all builder work is committed. Both must be valid commits in the current repo before Phase 5 starts.
- The `adversarial-review` skill owns the review block during the dryer; when it activates the loop it sets `review.active: true`, `round: 1`. That skill also owns `history` appends — one entry per completed round (`critical_high` / `advisory` are the counts of findings at those severities in that round's report). Entries are append-only, never rewritten; an optional `note` string is the entry schema's only sanctioned extension point; create the array if it is absent (in-flight 0.2.x state files predate it). Rounds legitimately split across `/clear`+resume session boundaries, so per-session dispatch counts undercount the loop — `history` is the authoritative round count for the final report (the round count is the highest `round` value in `history`, not its length — a protocol-failure `PENDING` entry shares its round number).
- Handle `consecutive_blocks` correctly in every rewrite: the guardrail hook (`check-review-loop.py`) increments it each time it blocks a stop; reset it to 0 whenever the loop makes progress (round advanced, verdict changed, or findings changed). Dropping the key weakens the hook's stop protection.
- **A verdict that is not in the state file does not exist.** No stop, no operator report, no dispatch may occur between parsing a verdict and committing it to the state file — one turn, both actions. The guardrail reads the file, not your intentions.
- **The loop nonce.** Whenever a review arms — including re-arming an existing inactive review block for a new loop — generate a fresh nonce: 8 lowercase hex characters, written as `review.nonce` (overwrite any prior value; never carry a nonce across loops). It persists for the whole loop, across every round and `/clear`+resume, and travels in every adversary dispatch as `NONCE: <value>`. The guardrail hook matches rendered verdicts by this tag, which is what keeps the literal `VERDICT: SHIP` strings in skill and agent prose from being mistaken for a real verdict.
- **`verdict: "PENDING"` means an adversary dispatch is in flight — at every round.** Round 1 starts PENDING; after every FIX-FIRST round, once the fixer's commits are verified and `head_sha` is refreshed, re-arm in one state write: `round: round + 1` and `verdict: "PENDING"` together, before re-dispatching the adversary. While verdict is PENDING, the write-guard hook mechanically blocks write-class tool calls from subagents — that is the enforcement layer behind the adversary's no-writes rule, so treat any adversary claim of having fixed the state file or the working tree as suspect and verify against git.
- On completion (SHIP or operator-accepted), set `review.active: false`, reset `consecutive_blocks: 0`, and leave the final `verdict` in place. The state file is the audit trail — the operator can reconstruct every transition from it after the fact.

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

Every AC must be verifiable by a named test or command. Every cited file path must exist — you verified them in Phase 1. When the plan is written, set `plan_path` in the state file to its absolute path.

**Planning is read-only.** The plan document itself is the only thing you write in this phase. No code changes, no config changes, no scaffolding, no "quick wins". If the research surfaced a trivially-fixable problem, it goes in the plan, not in the working tree.

## Phase 3: Plan-Review Gate

The plan does not proceed to execution until it survives review.

<!-- DISPATCH-PROTOCOL:BEGIN -->
#### Bounded pinned-first dispatch protocol (plan-reviewer and Phase 4 builder dispatches)

1. Invoke the named resource through Copilot's native agent/subagent delegation mechanism; do not call the Skill loader for agent names. Dispatch `plan-reviewer` (ed3d-orchestrate) with preferred model `gpt-5.5` and effort `xhigh`, expressed as `model="gpt-5.5"` and `reasoning_effort="xhigh"` overrides on the preferred attempt. Pass `PLAN_PATH` (absolute), `REPO_ROOT` (absolute), the exact role, prompt, and working directory. A one-time Auto fallback omits both overrides only after an explicit pre-start rejection identifying model, account availability, or effort support; preserve all other dispatch inputs. A started/no-verdict result uses the existing protocol-failure path with no model fallback, an ambiguous refusal is terminal, and rate-limit wait/retry/serialization remains separate. Report preferred success, fallback reason/retry/result, protocol failure, or ambiguity and print the full response.

The shared fallback rule is exactly one Auto fallback with both `model` and `reasoning_effort` overrides omitted; a fallback rejection is terminal. Rate-limit retries do not consume the model fallback; started/no-verdict uses protocol-failure without model fallback; ambiguity is terminal. Each lineage allows at most three semantic submissions, never issues the fallback twice, and never combines protocol retry with model fallback. Never combine protocol retry with model fallback.
2. Parse the verdict (`VERDICT: SHIP` / `VERDICT: FIX-FIRST`, `has_critical_or_high`).
3. On critical/high findings: fix the plan document, then re-dispatch `plan-reviewer` **once**.
4. If critical/high findings persist after the single re-review: **stop and present them to the operator.** The operator decides whether to revise again, proceed with acknowledged risks, or abandon. Do not proceed to execution on your own authority with open critical/high plan findings.

For the Phase 4 `task-implementor-fast` dispatch, use preferred model `gpt-5.6-luna` and effort `medium`, expressed as `model="gpt-5.6-luna"` and `reasoning_effort="medium"` overrides on the preferred attempt. Invoke the named resource through Copilot's native agent/subagent delegation mechanism; do not call the Skill loader for agent names. Preserve the exact implementation prompt, task, plan path, role, and working directory. A one-time Auto fallback omits both overrides only after an explicit pre-start rejection identifying model, account availability, or effort support.

The same bounded protocol applies to the `plan-reviewer` dispatch above: preferred `kimi-k3` / `high`, then one Auto fallback omitting both overrides only after an explicit pre-start model/account/effort rejection. A started/no-verdict result uses the existing protocol-failure path without model fallback, ambiguity is terminal without retry, and rate-limit wait/retry/serialization remains separate. Each lineage permits preferred, at most one Auto fallback, and at most one separately named protocol-failure re-dispatch; never duplicate a fallback or combine protocol retry with model fallback. Report preferred success, fallback reason/retry/result, protocol failure, or ambiguity, and print every full response.

The shared fallback rule is exactly one Auto fallback with both `model` and `reasoning_effort` overrides omitted; a fallback rejection is terminal. Rate-limit retries do not consume the model fallback; started/no-verdict uses protocol-failure without model fallback; ambiguity is terminal. Each lineage allows at most three semantic submissions, never issues the fallback twice, and never combines protocol retry with model fallback.

Site requirement: the Phase 4 `task-implementor-fast` dispatch is pinned-first with `gpt-5.6-luna` / `medium`, then one Auto fallback omitting both overrides only after an explicit pre-start model/account/effort rejection, preserving the exact implementation prompt, task, plan path, role, and working directory. Rate-limit and protocol-failure handling remain separate.

<!-- DISPATCH-PROTOCOL:END -->

## Context Handoff Gate (operator approval checkpoint after plan review)

Subagents run in isolated context windows, but **your** context accumulates every scout report, review, and builder response — the transparency rules require printing them all. Research and planning are the context-heavy phases; execution and review pile on more.

This gate is an **operator approval checkpoint**, not merely a context-management suggestion. It is **prompt-only guidance** — the mechanism implemented in this workflow's text — not **native Copilot runtime enforcement** (Copilot has no native facet-transition approval primitive for this boundary, so that enforcement is unavailable) and not **repository hook/script enforcement** (that mechanical backstop is deferred until a native builder-dispatch payload and identity are evidenced). A clean plan-review result does not by itself authorize execution: the plan-review pass is followed by this explicit approval checkpoint before any builder dispatch.

**Mandatory:** when the plan-review gate passes, the workflow stops at this approval checkpoint. Before dispatching ANY builder:

1. Verify the git baseline again. If no valid `HEAD` commit exists, create an initial commit now before proceeding.
2. Record `base_sha` in the state file from the current `HEAD` commit, then update the state file: `phase: "execute"` and `plan_path` set to the plan document's absolute path.
3. **End your turn** and present the operator approval checkpoint:
   - the plan-review verdict, in one or two lines, and
   - the two approval paths: reply **continue** to approve and start the builders in this context, or run `/clear` and then `/ed3d-orchestrate:orchestrate resume` to approve and continue with a fresh context.
4. Do not dispatch builders in the same turn in which the gate passed. Builder dispatch begins only after the operator's approval response (either `continue` or the `/clear` + resume) has been processed. This stop is safe: the guardrail hook only blocks stops while the review loop is active, which it is not yet.

On resume, the loop reads the state file (`phase: "execute"`) and the plan document at `plan_path` and starts Phase 4 directly. Completed phases are never repeated; nothing is lost to `/clear` — the plan, the commits, and the state file all live on disk.

The operator may also `/clear` + resume at any other phase boundary on their own initiative — the state file is current at every transition, so no cooperation from the loop is required.

## Phase 4: Execute

If you are resuming into this phase (`phase: "execute"` in the state file), read the plan document at `plan_path` first, then continue from here. Before dispatching any builder, verify `base_sha` exists in the state file and is a valid commit in the current repo; if it is missing, set it from the current `HEAD` before any implementation changes.

Fan out builders. One bounded task per dispatch — a builder gets a task it can complete fully with tests and a commit.

- **Independent tasks may run in parallel; dependent tasks must be sequenced.** If a dispatch fails with a provider rate-limit error, serialize: at most 2 in flight for the rest of the phase.
- Each dispatch prompt includes: the plan path (absolute), the task number, the working directory, and "Do not dispatch or invoke any subagents."

**Transparency rules (inherited from executing-an-implementation-plan):**

- The human cannot see what subagents return. You are their window into the work.
- After EVERY subagent completes, print its **full response** before taking any other action. No summarizing, no paraphrasing. Include test counts, issue lists, commit hashes, error messages. Exception: in the review loop, the verdict's state-file commit happens in the same turn, immediately before printing — the guardrail reads the file, not the transcript.
- Before every dispatch, say in 2–3 sentences what you're asking the agent to do and which phase it covers.

After all builders have reported, ensure implementation work is committed, record `head_sha` from the current `HEAD`, and verify `base_sha` and `head_sha` are both valid commits and differ unless the operator explicitly accepted a no-op task. Then update state: `phase: "review"` (`phase: "execute"` is set earlier, at the context-handoff gate).

## Phase 5: Tumble Dryer

Engage the `adversarial-review` skill (ed3d-orchestrate) only after verifying `base_sha` and `head_sha` are valid commits. It runs the review loop: adversary dispatch → verdict → fix critical/high → re-review, until SHIP or the round cap, then the operator circuit-breaker. The guardrail hook will block premature session stops while `review.active` is true — that is by design; if it blocks after an adversary verdict, commit the verdict to the state file immediately, including `consecutive_blocks: 0`, rather than fighting the hook.

## Phase 6: Assemble and Report

Before the final report, re-read `.ed3d/orchestrate-state.json` and verify the terminal state: `review.active: false`, `review.verdict: "SHIP"`, `review.consecutive_blocks: 0`, and the highest-round `review.history` entry matches the final verdict. If any check fails, fix the state file before reporting or stopping.

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
| "Gate passed, I'll just roll straight into the builders" | No. End your turn at the context-handoff gate and offer continue-vs-resume first. |
| "I'll summarize the builder's response for the user" | No. Print the full response. Always. |
| "The adversary didn't mention the prior issue, so it's fixed" | No. Silence is not confirmation. Carry it forward until explicitly confirmed fixed. |
| "Medium/low findings — I'll fix them all anyway to be safe" | Your call, but not required — this loop ships with advisory findings listed. Don't burn rounds on them. |
| "The stop hook keeps blocking; I'll just keep stopping" | The hook blocks while the review loop is active. Finish the loop (SHIP) or circuit-break (round > max_rounds, operator decides). |
| "I got VERDICT: SHIP — the loop is done, I'll report and stop" | No. Commit the verdict to the state file in the same turn first, reset `consecutive_blocks` to 0, re-read the state file, and only then report. A SHIP that the file doesn't record turns into guardrail blocks that leak into your reviewers' context. |
| "No argument was provided, so I need a new task" | Not if a state file exists. Resume the recorded loop first. |
| "The project exists now, so review can compare commits" | Not unless `base_sha` and `head_sha` are valid commits. Create/record the baseline before implementation and verify both SHAs before review. |
| "I'll dispatch a builder from a builder" | No. No nested subagents. Ever. You dispatch; they work and return. |
