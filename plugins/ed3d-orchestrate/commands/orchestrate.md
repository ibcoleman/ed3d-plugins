---
description: "Run the full ed3d-orchestrate loop on a task: scout-sweep research, plan document, plan-reviewer gate, builder fanout, adversarial tumble-dryer review, final report"
argument-hint: "[task-description]"
---

# Orchestrate

$1 contains the task description. If it is empty or vague, ask the operator what they want accomplished before proceeding — do not guess a task.

1. **Verify the working directory.** Confirm you are inside the repository where the work will happen (check for the VCS dir or an obvious project root). The loop maintains `.ed3d/orchestrate-state.json` in that repository's root, and the guardrail hook locates it by walking up from the working directory. If you are in the wrong place, `cd` to the right repository first.

2. **Engage the `orchestrating-the-loop` skill** (ed3d-orchestrate) and run it end-to-end for this task:

   Task: $1

3. Follow the skill exactly: research (scout-sweep) → plan document → plan-review gate → builder execution → adversarial review rounds → final report. Maintain `.ed3d/orchestrate-state.json` at every transition.
