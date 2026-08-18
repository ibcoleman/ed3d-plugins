---
name: "scout-sweep"
description: "Use when starting an orchestration loop (or any planning effort) that needs grounded research - fans out 2-4 focused scout dispatches to researcher agents in parallel, synthesizes their structured summaries, and has the orchestrator read the critical paths directly. Falls back to serial or small-batch dispatch on provider rate limits."
user-invocable: false
---

# Scout Sweep

Parallel research fanout for planning. Dispatch focused scouts, synthesize their reports, then read the critical paths yourself. The output feeds the plan document — bad research here becomes hallucinated plans later.

**Do not use nested subagents.** You dispatch first-level scouts. Scouts must not dispatch subagents; they return directly to you. (Every scout agent's own instructions say this too.)

## Step 1: Choose Focus Areas

Pick 2–4 non-overlapping focus areas based on the task. Typical splits:

- **Current codebase state** — what exists, where, and how it's structured
- **External dependencies** — current API/library behavior, from the internet
- **Prior art in the repo** — how similar features were built here before
- **Verification infrastructure** — test framework, build system, lint setup

Effort levels:

| Level | Scouts | When |
|-------|--------|------|
| Standard | 2 | Default for most tasks |
| Thorough | 3–4 | Novel domains, high-risk changes, unfamiliar codebase |

## Step 2: Dispatch the Scouts

Use the account's Auto/default model selection for scouts. Send no model or effort override; the account's CLI defaults decide both.

Match each focus area to the best researcher agent. Reference agents by both bare and qualified name in your dispatch so they resolve under any install:

- `codebase-investigator` (ed3d-research-agents) — codebase state, existing patterns
- `internet-researcher` (ed3d-research-agents) — current external knowledge, API docs
- `combined-researcher` (ed3d-research-agents) — both of the above synthesized
- `remote-code-researcher` (ed3d-research-agents) — how an external project actually implements something
- `haiku-general-purpose` (ed3d-basic-agents) — light general legwork

Each dispatch gets: the focus area, the specific questions to answer, and the required return format. Give each scout an explicit success criterion — "what counts as a complete answer for this area".

Scout prompt template (adapt the questions; keep the output contract):

```
You are scouting one focus area for a planning effort.

Focus area: [area]
Questions to answer:
1. [specific question]
2. [specific question]

Success looks like: [explicit criterion]

Return a structured summary with exactly these sections:

### Findings
Concrete facts, each with a source (file path with line numbers for local
findings; URL for external findings).

### File Paths
Every file you examined or that matters to this area, absolute paths.

### Critical Paths
The 2-5 files an implementer MUST read before touching this area, with one
line each on why.

### Confidence
What you verified directly vs. what you inferred. Say so honestly.

Do not dispatch or invoke any subagents. Do not write files; return your
findings in your response text only.
```

**Rate limits:** if any dispatch fails with a provider rate-limit or availability error, do not keep firing parallel dispatches — fall back to serial dispatch or batches of at most 2, and retry the failed scout once after a pause. Wide parallel bursts on a single provider trip limits; small batches don't.

## Step 3: Synthesize

Merge the scout reports into one research summary:

1. **Findings** — deduplicated, conflicts called out explicitly (if two scouts disagree, that's a finding, not noise)
2. **Critical paths** — union of the scouts' critical-path lists, ranked
3. **Open questions** — anything the scouts flagged as unverified

## Step 4: Read the Critical Paths Yourself

Do not plan from scout summaries alone. Open the top critical-path files and read the relevant sections directly. You are the one writing the plan; your claims about the codebase must be first-hand. If a scout's claim doesn't match what you read, the scout is wrong — note it and move on.

## Output

The research summary (findings, critical paths, open questions) becomes the grounding section of the plan document. Cite real file paths; anything you could not verify goes into the plan's Risks section as an explicit unknown, not into the findings.
