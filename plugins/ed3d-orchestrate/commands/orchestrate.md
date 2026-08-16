---
description: "Run the full ed3d-orchestrate loop on a task: scout-sweep research, plan document, plan-reviewer gate, builder fanout, adversarial tumble-dryer review, final report"
argument-hint: "[task-description]"
---

# Orchestrate

## Auto-resume mode

Before asking for a task, walk up from the current directory looking for `.ed3d/orchestrate-state.json`.

If `$1` is `resume`, or if `$1` is empty and the state file records an in-progress loop (`review.active` is true, or `review.verdict` is not `SHIP`):

1. Read the state file.
2. Report the recorded `task`, `phase`, `plan_path`, and review state to the operator in one short paragraph.
3. Read the plan document at `plan_path` (if set).
4. Engage the `orchestrating-the-loop` skill to continue from the recorded phase — do not restart or repeat completed phases.

If `$1` is `resume` and no state file exists, say so and ask for the task. If `$1` is empty and no state file exists, ask the operator what they want accomplished before engaging the loop. If the state file records a completed loop (`review.active: false` and `review.verdict: "SHIP"`), report it as completed — task and round count from `review.history` — and ask for the new task instead of resuming.

## Normal mode

$1 contains the task description. If it is empty or vague after the auto-resume check above, ask the operator what they want accomplished — do not guess a task.

1. **Verify the working directory and git baseline.** Confirm you are inside the repository where the work will happen. The loop requires a local git repository with at least one commit because adversarial review needs a valid `BASE_SHA..HEAD_SHA` range. If no git repo exists and the directory is empty or the task is to create a new project, initialize git and create an initial commit before research. If no git repo exists in a non-empty directory, ask before initializing. If a git repo exists but has no commits, create an initial commit before implementation. The loop maintains `.ed3d/orchestrate-state.json` in that repository's root, and the guardrail hook locates it by walking up from the working directory. If you are in the wrong place, `cd` to the right repository first.

2. **Engage the `orchestrating-the-loop` skill** (ed3d-orchestrate) and run it end-to-end for this task:

   Task: $1

3. Follow the skill exactly: research (scout-sweep) → plan document → plan-review gate → builder execution → adversarial review rounds → final report. Maintain `.ed3d/orchestrate-state.json` at every transition, record the plan document's absolute path as `plan_path` as soon as it is written so resume can find it, and record a valid `BASE_SHA` before builder execution so review has a real diff range.
