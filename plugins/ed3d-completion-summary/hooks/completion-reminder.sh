#!/bin/sh
# completion-reminder.sh — GitHub Copilot CLI `sessionStart` command hook.
#
# Injects a one-line advisory nudge into the session at start, reminding the
# agent to prepare an executive handoff (the work-completion-summary skill)
# when a substantial work item completes.
#
# CONTRACT
#   stdin : a single JSON object, ignored entirely. Two dialects are seen in
#           the wild; both are irrelevant because the output is constant:
#             - camelCase  : {"sessionId":..., "timestamp":..., "cwd":...,
#                             "source":"startup"|"resume"|"new",
#                             "initialPrompt":...}
#             - VS Code    : {"hook_event_name":"SessionStart",
#                             "session_id":..., "cwd":...,
#                             "initial_prompt":...}
#   stdout: always the EXACT single line below, then exit 0.
#   The payload is read and discarded; it never varies the output, so empty or
#   malformed stdin (including binary garbage) still yields this same line and
#   exit 0. Deterministic constant output by design.
#
# FAIL-OPEN SEMANTICS
#   sessionStart is advisory. A non-zero exit or timeout (this package ships
#   timeoutSec: 5) is logged by the CLI and the session continues. Never block,
#   never write files, never touch the network, never inspect the repository.
#   No external JSON parser is required (no parsing is done).

set -u

# Read stdin fully and discard it. `cat` never examines or parses the payload;
# absent or malformed stdin simply yields empty input, which is fine — the
# output never depends on it.
cat >/dev/null

# Emit the exact constant reminder line (single line, trailing newline).
printf '%s\n' '{"additionalContext": "Session reminder: when a substantial work item completes in this session, prepare the work-completion-summary executive handoff (invoke the work-completion-summary skill) before stopping. Advisory only - never block on it."}'

exit 0
