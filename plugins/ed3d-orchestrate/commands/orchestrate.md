---
description: "Run the full ed3d-orchestrate loop on a task: scout-sweep research, plan document, plan-reviewer gate, builder fanout, adversarial tumble-dryer review, final report"
argument-hint: "[task-description]"
---

# Orchestrate

## Auto-resume mode

Before asking for a task, locate `.ed3d/orchestrate-state.json` with direct file reads only — never a search: inside a git repository, resolve the root with `git rev-parse --show-toplevel` and read `<root>/.ed3d/orchestrate-state.json`; outside one, check `.ed3d/orchestrate-state.json` in the current directory and, if absent, its immediate parent (only if still within the same project tree). Do not use recursive glob patterns or `find`-style searches, and never request access to directories outside the project — an unbounded walk-up prompts for `/` access (observed in 0.3.1's first live run).

If `$1` is `resume`, or if `$1` is empty and the state file records an in-progress loop (`review.active` is true, or `review.verdict` is not `SHIP`):

1. Read the state file, then `cd` to the repository root you resolved it from — `/clear` preserves the shell's working directory (a live resume once ran from `docs/`), so make every subsequent git command and state-file write root-relative.
2. Report the recorded `task`, `phase`, `plan_path`, and review state to the operator in one short paragraph.
3. Read the plan document at `plan_path` (if set).
4. Engage the `orchestrating-the-loop` skill to continue from the recorded phase — do not restart or repeat completed phases.

If `$1` is `resume` and no state file exists, say so and ask for the task. If `$1` is empty and no state file exists, ask the operator what they want accomplished before engaging the loop. If the state file records a completed loop (`review.active: false` and `review.verdict: "SHIP"`), report it as completed — task and round count from `review.history` — and ask for the new task instead of resuming.

## Normal mode

$1 contains the task description. If it is empty or vague after the auto-resume check above, ask the operator what they want accomplished — do not guess a task.

1. **Verify the working directory and git baseline.** Confirm you are inside the repository where the work will happen. The loop requires a local git repository with at least one commit because adversarial review needs a valid `BASE_SHA..HEAD_SHA` range. If no git repo exists and the directory is empty or the task is to create a new project, initialize git and create an initial commit before research. If no git repo exists in a non-empty directory, ask before initializing. If a git repo exists but has no commits, create an initial commit before implementation. The loop maintains `.ed3d/orchestrate-state.json` in that repository's root — read it there directly (the guardrail hook does its own in-process walk-up from the working directory; that is its mechanism, not an instruction to you). If you are in the wrong place, `cd` to the right repository first.

2. **Engage the `orchestrating-the-loop` skill** (ed3d-orchestrate) and run it end-to-end for this task:

   Task: $1

3. Follow the skill exactly: research (scout-sweep) → plan document → plan-review gate → **operator approval checkpoint** → builder execution → adversarial review rounds → final report. The plan-review pass is followed by an explicit approval checkpoint before any builder dispatch: the orchestrator ends its turn and offers the two approval paths — reply **continue** to proceed in the same context, or `/clear` then resume with a fresh context. Maintain `.ed3d/orchestrate-state.json` at every transition, record the plan document's absolute path as `plan_path` as soon as it is written so resume can find it, and record a valid `BASE_SHA` before builder execution so review has a real diff range.
