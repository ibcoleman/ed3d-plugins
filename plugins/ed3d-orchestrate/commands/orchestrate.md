---
description: "Run the full ed3d-orchestrate loop on a task: scout-sweep research, plan document, plan-reviewer gate, builder fanout, adversarial tumble-dryer review, final report"
argument-hint: "[task-description]"
---

# Orchestrate

## Resume mode

If `$1` is `resume`: read `.ed3d/orchestrate-state.json` from the working directory (walk up parent directories to find it). If it exists and records an in-progress loop, report the recorded `task`, `phase`, and review state to the operator, read the plan document at `plan_path` (if set), and engage the `orchestrating-the-loop` skill to continue from the recorded phase — do not restart or repeat completed phases. If no state file exists, fall through to normal mode and ask for a task.

## Normal mode

$1 contains the task description. If it is empty or vague, ask the operator what they want accomplished before proceeding — do not guess a task.

1. **Verify the working directory.** Confirm you are inside the repository where the work will happen (check for the VCS dir or an obvious project root). The loop maintains `.ed3d/orchestrate-state.json` in that repository's root, and the guardrail hook locates it by walking up from the working directory. If you are in the wrong place, `cd` to the right repository first.

2. **Engage the `orchestrating-the-loop` skill** (ed3d-orchestrate) and run it end-to-end for this task:

   Task: $1

3. Follow the skill exactly: research (scout-sweep) → plan document → plan-review gate → builder execution → adversarial review rounds → final report. Maintain `.ed3d/orchestrate-state.json` at every transition, and record the plan document's absolute path as `plan_path` as soon as it is written so `resume` can find it.
