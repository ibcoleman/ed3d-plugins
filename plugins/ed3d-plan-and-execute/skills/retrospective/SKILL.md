---
name: retrospective
description: Use when a development attempt hits a dead end -- gathers git history, design plan assumptions, and transcript evidence to produce a structured retrospective document that informs the next design attempt
user-invocable: true
---

# Retrospective

## Overview

Capture lessons learned when a development loop hits a dead end. Performs automated evidence gathering via parallel subagents (git analysis, design plan comparison, transcript review), synthesizes findings, asks targeted questions to fill gaps, and produces a structured retrospective document.

**Announce at start:** "I'm using the retrospective skill to capture lessons learned and produce a retrospective document."

## Inputs

Auto-detected with overrides:

1. **Current branch** -- from `git branch --show-current`
2. **Base branch** -- defaults to `main`
3. **Design plan path** -- auto-detected by scanning `docs/design-plans/` for a file matching the branch slug

At start, detect inputs and confirm with user:

```
Detected:
- Branch: {branch_name}
- Base: main
- Design plan: {path or "none found"}

Use AskUserQuestion:
  Question: "Are these inputs correct?"
  Options:
    - "Yes, proceed"
    - "Change base branch"
    - "Specify design plan path"
```

**Design plan auto-detection algorithm:**
1. Get current branch name
2. Strip common prefixes: `skunkworks/`, `feature/`, `bugfix/`, `hotfix/`, any `TLMDEV-XXXX-` prefix
3. Convert to lowercase slug (replace `/` and `_` with `-`)
4. Search `docs/design-plans/` for files containing the slug in their filename (after stripping `YYYY-MM-DD-` prefix)
5. If multiple matches, present all via AskUserQuestion
6. If no matches, proceed without design plan (graceful degradation)

**Output path derivation:**
1. If design plan found: extract slug from design plan filename (everything after `YYYY-MM-DD-`, excluding `.md`). Example: `vite8-integration` from `2026-03-13-vite8-integration.md`
2. If no design plan: derive from sanitized branch name (strip prefixes, lowercase, hyphens)
3. Output: `docs/design-plans/{slug}-retrospective.md`
4. **Collision handling:** If `{slug}-retrospective.md` exists, append counter: `{slug}-retrospective-2.md`, `{slug}-retrospective-3.md`, etc.

## Task Tracking

**REQUIRED: Create task tracker at start using TaskCreate.**

```
TaskCreate: "Phase 1: Evidence Gathering" -- Dispatch parallel subagents
TaskCreate: "Phase 2: Synthesis" -- Cross-reference subagent reports
  -> TaskUpdate: addBlockedBy: [Phase 1]
TaskCreate: "Phase 3: Targeted Q&A" -- Present findings and ask evidence-based questions
  -> TaskUpdate: addBlockedBy: [Phase 2]
TaskCreate: "Phase 4: Document Generation" -- Write retrospective to docs/design-plans/
  -> TaskUpdate: addBlockedBy: [Phase 3]
```

Use TaskUpdate to mark each phase in_progress before starting and completed when done.

## Phase 1: Evidence Gathering

Mark "Phase 1: Evidence Gathering" as in_progress.

Dispatch three subagents **in parallel** (single message with multiple Agent tool calls). Each subagent receives the branch name, base branch, and any relevant paths.

### Subagent 1: Git Analyst

```
Agent tool:
  subagent_type: ed3d-basic-agents:haiku-general-purpose
  model: haiku
  description: "Git analysis for retrospective"
  prompt: |
    You are the Git Analyst for a retrospective. Analyze the git history
    of branch "{branch_name}" compared to base "{base_branch}".

    Run these commands and analyze the output:

    1. Full commit arc:
       git log --oneline {base_branch}..HEAD

    2. Overall scope:
       git diff --stat {base_branch}..HEAD

    3. Churn hot spots -- files modified in 3+ separate commits:
       git log --name-only --pretty=format: {base_branch}..HEAD | sort | uniq -c | sort -rn | head -20

    4. Revert and fixup detection:
       git log --oneline {base_branch}..HEAD | grep -iE "revert|fixup|squash"

    5. Workaround pattern detection (search commit messages):
       git log --oneline {base_branch}..HEAD | grep -iE "workaround|hack|bandaid|attempt|temporary|revert"
       NOTE: Do NOT match bare "fix:" -- that is a standard conventional commit prefix.

    Produce a structured report with these sections:

    ## Commit Arc
    Narrative summary of the branch progression (what was attempted, in what order).

    ## Churn Hot Spots (Top 10)
    | File | Change Count | Nature of Changes |
    |------|-------------|-------------------|

    ## Revert/Fixup Pairs
    List any commits that undo or patch previous commits, with the original
    and the correction.

    ## Workaround Patterns
    Commit messages suggesting workarounds or temporary fixes.

    ## Summary
    2-3 sentence narrative of the branch's progression.
```

### Subagent 2: Design Comparator

**Skip if no design plan was found.** Note "No design plan found -- skipping Design Comparator" in synthesis.

```
Agent tool:
  subagent_type: ed3d-basic-agents:sonnet-general-purpose
  model: sonnet
  description: "Design plan comparison for retrospective"
  prompt: |
    You are the Design Comparator for a retrospective. Read the design plan
    and categorize each assumption or architectural decision.

    Design plan: {design_plan_path}
    Implementation plan directory (if exists): docs/implementation-plans/

    Read the design plan. For each assumption or architectural decision
    in the design, categorize it:

    - **Validated** -- held up during implementation
    - **Partially Wrong** -- needed adjustment but core idea survived
    - **Invalidated** -- fundamentally incorrect, caused rework
    - **Untested** -- never got far enough to validate

    To determine categories, also check:
    - Git history: git log --oneline {base_branch}..HEAD
    - Implementation plan phases (if they exist in docs/implementation-plans/)
    - Files changed: git diff --stat {base_branch}..HEAD

    Cross-reference with git churn -- files modified many times often
    indicate invalidated assumptions.

    Produce a structured report:

    ## Assumption Audit

    | # | Assumption | Reality | Impact | Category |
    |---|-----------|---------|--------|----------|
    (number each assumption sequentially)

    ## Narrative
    Which decisions held? Which broke? What was the biggest surprise?

    ## Untested Assumptions
    List assumptions that were never reached -- these carry forward
    as risks for the next attempt.
```

### Subagent 3: Transcript Reviewer

**Skip if any of these conditions are true:**
- No transcript files found in session directory
- `reduce-transcript.py` cannot be located

Note the skip reason in synthesis.

**Transcript discovery (orchestrator resolves paths before dispatching):**

```bash
# 1. Find the project session directory
#    Hash the project path the same way Claude Code does
PROJECT_DIR=$(git rev-parse --show-toplevel)

# 2. List session directory candidates
ls -la ~/.claude/projects/

# 3. Find the correct project directory (match by examining contents)
#    Look for directories that contain session files related to this project

# 4. List .jsonl transcript files, sorted by modification time
ls -lt ~/.claude/projects/{project-hash}/*.jsonl | head -10

# 5. Resolve reduce-transcript.py path (runtime discovery -- do NOT hardcode)
REDUCE_SCRIPT=$(find ~/.claude/plugins -path "*/ed3d-session-reflection/scripts/reduce-transcript.py" 2>/dev/null | head -1)
if [ -n "$REDUCE_SCRIPT" ]; then
    echo "Script found at: $REDUCE_SCRIPT"
else
    echo "Script not found -- skip Transcript Reviewer"
fi
```

**After resolving paths, dispatch subagent with absolute paths:**

```
Agent tool:
  subagent_type: ed3d-basic-agents:sonnet-general-purpose
  model: sonnet
  description: "Transcript review for retrospective"
  prompt: |
    You are the Transcript Reviewer for a retrospective on the
    "{branch_name}" branch (feature: {feature_description}).

    Your job is to find pivot moments, discovery moments, and workaround
    discussions in recent session transcripts.

    **IMPORTANT:** Transcripts are scoped by recency, not by branch.
    Some sessions may be about unrelated work. Filter for content relevant
    to the feature being retrospected. Discard unrelated sessions.

    Step 1: Reduce each transcript (REQUIRED -- raw JSONL will exceed context)

    For each transcript file, run:
      python3 {reduce_script_path} "{transcript_path}" "/tmp/retro-{session_id}/reduced-{N}.txt"

    Transcript files to process (most recent first):
    {list of absolute paths to .jsonl files}

    Step 2: Read each reduced transcript and scan for:

    - **Pivot moments** -- where conversation shifted from "working" to
      "not working" (e.g., "this approach won't work because...")
    - **Discovery moments** -- where a new constraint was first identified
      (e.g., "I just realized that X doesn't support Y")
    - **Workaround discussions** -- where shims or hacks were proposed
      (e.g., "as a workaround, we could...")

    Step 3: Produce a structured report:

    ## Key Moments (5-10 most significant)

    | # | Type | Session | Summary |
    |---|------|---------|---------|
    (One sentence each with enough context to understand the significance)

    ## Timeline
    Chronological narrative of how understanding evolved across sessions.

    ## Patterns
    Any recurring themes (e.g., same constraint discovered multiple ways,
    same workaround attempted repeatedly).
```

After all subagents complete, mark "Phase 1: Evidence Gathering" as completed.

## Phase 2: Synthesis

Mark "Phase 2: Synthesis" as in_progress.

**Perform synthesis inline** (not a subagent) -- the orchestrator needs this context for Q&A.

Cross-reference the subagent reports to identify:

### 1. Assumption-to-Reality Gaps
Highest-signal lessons. Look for the triple match:
- Invalidated assumption (Design Comparator) +
- Heavy churn in same area (Git Analyst) +
- Pivot moment (Transcript Reviewer)

### 2. Cascade Failures
Reconstruct chains: trigger -> consequence -> workaround -> next problem -> ...
Built from evidence across all three reports.

### 3. Unforced Errors
Git churn in areas the design didn't make explicit assumptions about.
Blind spots rather than wrong assumptions.

### 4. What Worked
Assumptions that held, approaches that succeeded. Preserve for next attempt.

**If only Git Analyst reported** (graceful degradation): Focus synthesis on churn
patterns and commit arc narrative. Note that Q&A phase will carry more weight
to fill gaps from missing design/transcript analysis.

Mark "Phase 2: Synthesis" as completed.

## Phase 3: Targeted Q&A

Mark "Phase 3: Targeted Q&A" as in_progress.

Present draft findings to the user -- a concise summary of the synthesis:
- Top 3-5 findings (assumption-to-reality gaps, cascade failures, what worked)
- Evidence supporting each finding

Then ask **2-4 targeted questions** derived from specific evidence gaps.

**These must NOT be generic retrospective questions.** Each question must:
- Reference specific evidence (file names, commit messages, transcript moments)
- Address a gap where automated analysis couldn't determine the full story

**Examples of good questions:**
- "The git history shows the module loading strategy changed three times,
  but the design only considered one approach. Were there constraints you
  discovered that aren't captured in any artifact?"
- "Files A, B, and C were each modified 6+ times. Is there a shared root
  cause, or were these independent issues?"

**Examples of bad questions (DO NOT ASK THESE):**
- "What did you learn?" (too generic)
- "What would you do differently?" (premature -- save for recommendations)
- "Was this a good use of time?" (not evidence-based)

Use AskUserQuestion for each question (or present all at once if they're
independent).

Incorporate user answers into the synthesis. These answers inform the
Recommendations section of the final document.

Mark "Phase 3: Targeted Q&A" as completed.

## Phase 4: Document Generation

Mark "Phase 4: Document Generation" as in_progress.

Write the retrospective document to the output path determined during input
detection. Use the Write tool.

### Document Structure

```markdown
# Retrospective: {Feature Name}

**Date:** YYYY-MM-DD
**Branch:** {branch-name}
**Design Plan:** {link to original design doc, or "None"}
**Outcome:** Dead end / Partial success / Pivot needed

## Executive Summary
2-3 sentences: what was attempted, why it didn't work, the single biggest lesson.

## What Was Attempted
Brief narrative arc of the branch -- the progression of approaches,
not a commit-by-commit log.

## Assumption Audit

| # | Assumption (from design) | Reality | Impact | Category |
|---|--------------------------|---------|--------|----------|
| 1 | ... | ... | ... | Invalidated |
| 2 | ... | ... | ... | Partially Wrong |
| 3 | ... | ... | ... | Validated |

(If no design plan was available, note: "No design plan was available for
this attempt. Assumptions below are inferred from git history and user input.")

## Cascade Failures
Numbered chains showing how one wrong assumption led to downstream problems.

1. **[Trigger]** -> [Consequence] -> [Workaround] -> [Next Problem]
2. ...

## Discoveries
Constraints, behaviors, limitations that only surfaced during implementation.
The "expensive knowledge" items. Bullet list, one per discovery.

## What Worked
Approaches and assumptions that held up. Keep these for the next attempt.
Bullet list, one per item.

## Recommendations for Next Attempt
Specific, actionable guidance for the next design phase:
- "Do X instead of Y"
- "Validate Z before committing to an approach"
- "The real constraint is W, design around it"

## Raw Evidence
<details><summary>Git hot spots (top 10 by change frequency)</summary>

{Condensed from Git Analyst report -- table of files and change counts}

</details>

<details><summary>Key transcript moments</summary>

{Condensed from Transcript Reviewer -- one sentence each, 5-10 items}
{If no transcripts were available: "No session transcripts were available for this retrospective."}

</details>
```

**The Recommendations for Next Attempt section is the highest-value section.**
Spend the most effort here. It must be:
- Specific (not "plan better" but "validate X constraint before choosing Y approach")
- Actionable (someone starting fresh can follow these)
- Evidence-based (tied to discoveries and cascade failures above)

After writing, verify the file exists:

```bash
test -f "{output_path}" && echo "Retrospective written successfully" || echo "ERROR: File not written"
```

Mark "Phase 4: Document Generation" as completed.

## Common Rationalizations -- STOP

| Thought | Reality |
|---------|---------|
| "The branch only has a few commits, skip transcript review" | Few commits can still represent weeks of work with many sessions. Check for transcripts. |
| "I can combine synthesis and Q&A to save time" | Synthesis must complete BEFORE Q&A -- the questions are derived from synthesis gaps. Combining them means generic questions. |
| "I'll write the document first, then ask questions" | User answers change the document. Write after Q&A, not before. |
| "There's no design plan so this retrospective won't be useful" | Git history alone produces a useful retrospective. The minimum viable output (churn analysis + user Q&A) is still valuable. |
| "The user seems to know what went wrong, just ask them" | Automated evidence catches things humans forget or rationalize away. Always gather evidence first. |
```
