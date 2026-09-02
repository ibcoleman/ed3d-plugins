---
name: work-completion-summary
description: "Invoke when a substantial work item — an implementation, investigation, or review — is declared complete and the operator needs an executive handoff. Also user-invocable at session end. Prepare a concise executive summary that distinguishes verified facts from inference, planned work, and remaining risk."
---

# Work Completion Summary

Prepare a concise executive handoff for the completed work. The default target is roughly one page; expand to two pages only when the change has meaningful operational, migration, or risk details.

## Ground truth first

Before writing the summary:
1. Inspect the final working tree, relevant files, tests, release metadata, and review results.
2. Distinguish verified facts from inference, planned work, and remaining risk.
3. Do not claim a feature is complete merely because an implementation agent says so; verify the important acceptance criteria yourself.
4. If the work is not actually complete, say so plainly and change the heading to `Status: Incomplete` or `Status: Blocked`.
5. Treat uncommitted changes, untracked files, failed checks, and stale documentation as relevant status facts.

## Summary format

Use this structure unless the operator requests another format:
- `# [Work item] — Executive Summary` heading
- `## Status` — one of: Complete, Complete with follow-up, Incomplete, or Blocked; include the release/version or commit reference when verified.
- `## What we did` — delivered behavior in plain language; important files/interfaces/workflows/user-visible changes, not a file inventory.
- `## Why we did it` — original problem, observed evidence, constraints, the tradeoff behind the chosen solution; which account/environment/user paths are covered.
- `## How to use it` — copy-pasteable commands or prompts when applicable; prerequisites, configuration, expected behavior, fallback behavior, how to tell whether it worked; prefer a short numbered procedure.
- `## Verification` — checks actually run and their results; manual validation still required; never convert static validation into a claim of live integration success.
- `## Limitations and follow-up` — remaining risks, unsupported paths, migration/reinstall requirements, known warnings, next recommended action; keep advisory items separate from blockers.

## Communication rules

- Lead with the outcome and status, not the process.
- Explain technical terms the intended reader may not know.
- Use exact error messages, version numbers, and commands when they matter.
- Say "the implementation instructs/retries/reports" when behavior is procedural prompt guidance rather than mechanically enforced runtime behavior.
- Do not invent metrics, account behavior, test results, commits, or deployment status.
- Do not hide important caveats to make the result sound finished.
- Avoid reproducing secrets, tokens, private paths, or sensitive prompt contents.

## Optional durable artifact

If the operator asks for a file, write the summary to the requested path. If no path is given, propose a sensible project-local location such as `docs/completion-summaries/YYYY-MM-DD-<slug>.md`; do not create it silently when the request was only for an on-screen summary.

## Optional email

Only send email when the operator explicitly asks for it. Confirm the final recipient, subject, and body before sending when any of those are ambiguous. If the environment has no configured email tool, say so plainly instead of inventing a workaround. Report whether sending succeeded or failed.

## Completion prompt

When a large work item is nearing completion, the agent driving the work should invoke this skill before the final response and follow the "Ground truth first" section before claiming the work complete.

> Prepare the executive completion summary now. Verify the implementation, tests, review outcome, release state, and remaining risks. Explain what we did, why we did it, and how to use it. Do not claim live validation unless it was run.

If the work involved a review loop, include the final verdict and unresolved advisory findings. If it involved a release, include the version and installation/update instructions.

## Invocation (Copilot CLI)

The model may invoke this skill near work completion based on the description, or the user invokes it directly as `/work-completion-summary` (list with `/skills list`). The companion sessionStart hook (this package's `hooks/`) injects a session-start reminder to use this skill; the reminder is advisory only.
