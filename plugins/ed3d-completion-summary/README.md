# ed3d-completion-summary — Copilot CLI hook + Agent Skill

Executive handoffs for work completed under GitHub Copilot CLI: a `sessionStart` command hook that injects a one-line advisory reminder into the session at start, plus an Agent Skill (`skills/work-completion-summary/SKILL.md`) that the agent invokes when a substantial work item — an implementation, investigation, or review — completes. The skill prepares a concise, ground-truth-first executive summary; the hook is a non-blocking nudge to actually use it.

> **This is a GitHub Copilot CLI package only.** It is not a Claude Code plugin, and Claude Code is not supported — the `sessionStart` hook and skill target the Copilot CLI v1 hook schema and payload/contract only. Do not try to register this package as a Claude Code plugin.

## Status: INACTIVE BY DEFAULT

**This package is inactive until explicitly activated.** The Copilot artifacts are **not deployed anywhere** — no hook file is installed into any target repo's `.github/hooks/` or `~/.copilot/hooks/`, and the skill is not copied into any skills directory. Installing or vendoring this package does **not** automatically deploy the hook or skill; treat the artifacts as documentation for opt-in activation.

| Aspect | Status |
|---|---|
| Copilot CLI hook installed | No (requires explicit copy/deployment) |
| Agent Skill installed | No (requires explicit skill installation/discovery) |
| Reminder active | Only after deployment |

## Layout

```
plugins/ed3d-completion-summary/
├── README.md                            # this file
├── .claude-plugin/
│   └── plugin.json                      # catalog metadata (0.1.0; Copilot-only)
├── hooks/
│   ├── completion-reminder.json         # Copilot CLI v1 sessionStart hook config (repo-local; timeoutSec 5)
│   └── completion-reminder.sh           # the reminder script (POSIX sh; constant output)
├── skills/
│   └── work-completion-summary/
│       └── SKILL.md                     # the Agent Skill (executive handoff format)
└── tests/
    ├── README.md                        # offline test-suite documentation
    ├── run-all.sh                       # runner over all suites
    ├── test-completion-reminder.sh      # exact output contract + scope
    ├── test-package-layout.sh           # package layout / skill / hook / docs
    └── lib/
        └── harness.sh                   # POSIX harness + runner
```

`hooks/completion-reminder.json` is the **only** shipped runtime hook config — there is no `hooks.json`. The hook is a single Copilot CLI v1 `sessionStart` config plus its reminder script.

## Install / Copy Paths

There are two artifacts to install: the **hook** (session-start nudge) and the **skill** (agent-facing guidance). They install to different locations.

### 1. Copilot `sessionStart` hook — copy path

The shipped artifacts are `hooks/completion-reminder.json` (config) and `hooks/completion-reminder.sh` (the script). The config is **repo-local only as shipped**: it calls the script with a **relative** path (`./completion-reminder.sh`) and sets `cwd` to a **repo-root-relative** `.github/hooks`. Both paths resolve against the repository root, so this config works only when both files live in `.github/hooks/` of the target repo.

- **Repo-level (the only deployable form as shipped):** copy both files into `.github/hooks/` of the target repository so the reminder travels with the repo and is reviewable:
  ```bash
  cp plugins/ed3d-completion-summary/hooks/completion-reminder.json .github/hooks/
  cp plugins/ed3d-completion-summary/hooks/completion-reminder.sh  .github/hooks/
  ```
- **User-level (`~/.copilot/hooks/`) requires an absolute script path — not supported as shipped.** Because `./completion-reminder.sh` and `cwd: ".github/hooks"` are repo-relative, copying the config to `~/.copilot/hooks/completion-reminder.json` unchanged resolves the script against the wrong location and the hook fails. To install a user-level hook you must edit `completion-reminder.json` so the `bash` field is an **absolute path** to `completion-reminder.sh` (and either remove `cwd` or set it to the script's absolute directory):
  ```bash
  cp plugins/ed3d-completion-summary/hooks/completion-reminder.sh ~/.copilot/hooks/
  cp plugins/ed3d-completion-summary/hooks/completion-reminder.json ~/.copilot/hooks/
  # then edit ~/.copilot/hooks/completion-reminder.json: "bash": "/abs/path/to/completion-reminder.sh", drop "cwd"
  ```
  If `COPILOT_HOME` is set, use `$COPILOT_HOME/hooks/` instead of `~/.copilot/hooks/`. (Native Windows uses `%USERPROFILE%\.copilot\hooks\` — not supported by this bash-only hook.)
- The config file must be valid JSON with top-level `version` and `hooks` keys (schema below). The filename may be anything but must end in `.json`; the script path inside it is what matters.

### 2. Agent Skill — copy path

Copilot CLI discovers Agent Skills by name. Copy the whole `skills/work-completion-summary/` directory (the folder named `work-completion-summary` containing `SKILL.md`) to a skills location Copilot CLI scans.

- **User-level (recommended, available in every repo):**
  ```
  cp -r plugins/ed3d-completion-summary/skills/work-completion-summary ~/.copilot/skills/
  ```
  → `~/.copilot/skills/work-completion-summary/SKILL.md`
- **Repo-local:** copy to `.github/skills/work-completion-summary/` in the target repository.
- **Verify:** the destination file must be named `SKILL.md` (exact case). Renaming to `skill.md` breaks discovery.
- After copying, restart the `copilot` session so the skill registry is refreshed (or run `/skills reload` to refresh without a restart).

## Copilot CLI v1 Hook Schema (exact)

One JSON object (this is exactly the shipped `hooks/completion-reminder.json`):

```json
{
  "version": 1,
  "hooks": {
    "sessionStart": [
      {
        "type": "command",
        "bash": "./completion-reminder.sh",
        "timeoutSec": 5,
        "cwd": ".github/hooks"
      }
    ]
  }
}
```

> Note the **relative** `bash` path and repo-root-relative `cwd` — this config deploys repo-locally into `.github/hooks/`. The timeout is **5 seconds** (`timeoutSec: 5`), not the Copilot CLI default of 30.

**Field contract:**

| Field | Value | Notes |
|---|---|---|
| `version` | `1` | Required top-level. Copilot CLI skips files without `version: 1`. |
| `hooks` | object | Each key is a trigger; each value is an array of hook entries. |
| `sessionStart` | array | The trigger this package uses: one command hook. |
| `type` | `"command"` | Command hook. (HTTP hooks exist but are always fail-open.) |
| `bash` | `"./completion-reminder.sh"` | Bash script for Linux/macOS/WSL. Relative here, so it resolves against `cwd` (repo-local). |
| `powershell` | (absent) | Deliberately omitted — POSIX/WSL only. On native Windows no powershell command is defined, so the hook is not expected to run. |
| `cwd` | `".github/hooks"` | Working directory for the hook process (repo-root relative). Optional. |
| `timeoutSec` | `5` | Seconds before the hook is killed. This package ships **5 seconds**. |
| `matcher` | (absent) | **`sessionStart` does NOT take a `matcher`.** `matcher` applies only to `notification`, `permissionRequest`, `postToolUse`, `preCompact`, `preToolUse`, `subagentStart`. |

### sessionStart input payload (both dialects)

A `sessionStart` hook receives a single JSON object on **stdin**. Two dialects are observed:

- **camelCase (CLI):**
  ```json
  {
    "sessionId": "…",
    "timestamp": 1234567890,
    "cwd": "/abs/path/to/cwd",
    "source": "startup" | "resume" | "new",
    "initialPrompt": "…"
  }
  ```
- **VS Code (snake_case):**
  ```json
  {
    "hook_event_name": "SessionStart",
    "session_id": "…",
    "initial_prompt": "…",
    "cwd": "…",
    "source": "startup" | "resume" | "new",
    "timestamp": "2026-08-31T12:00:00.000Z"
  }
  ```

This package's hook **ignores the payload entirely** (see Behavior), so dialect and shape differences are irrelevant to its output.

### sessionStart output contract (the exact emitted line)

A `sessionStart` hook can inject `additionalContext` into the session. This package ships the top-level, documented-pattern shape:

```
{"additionalContext": "Session reminder: when a substantial work item completes in this session, prepare the work-completion-summary executive handoff (invoke the work-completion-summary skill) before stopping. Advisory only - never block on it."}
```

`completion-reminder.sh` prints **exactly** this single line (with a trailing newline) on stdout and exits `0`, regardless of input.

## Behavior

The hook is **deterministic constant-output and advisory-only**.

- **Reads stdin fully, discards it.** It does not parse or inspect the payload, so empty, malformed, or binary-garbage stdin yields the same output and exit `0`. The payload never varies the output.
- **Emits the exact reminder line above** on stdout and exits `0`. No `jq`, no `python`, no parsing.
- **Never writes files, never touches the network, never inspects the repository.**
- **Fail-open:** `sessionStart` is advisory. A non-zero exit or timeout is logged by Copilot CLI and the session continues — the hook can never block a session. Do not rely on it for any safety invariant.

## Design rationale

- **Why `sessionStart`?** It is the supported mechanism for injecting a session-start nudge. The alternative command hook `userPromptSubmitted` **drops its output in Copilot CLI**, so it is unusable for context injection — a refuted mechanism. `sessionStart` is the only supported place to add a start-of-session reminder.
- **Why no prompt file?** Prompt files (`*.prompt.md`) are an **IDE-only feature and are not supported in Copilot CLI**. This package therefore ships an **Agent Skill** instead, which is slash-invocable in the CLI as `/work-completion-summary` (and lists under `/skills list`).
- **Why not a blocking `agentStop` hook?** The reminder is an advisory nudge, not a safety invariant. A blocking stop-hook would interrupt the agent at every stop (a spam/hazard cost documented in this repo's orchestrate history) for no enforcement value. The `sessionStart` approach is one quiet line at a session's start and never blocks.
- **Why `timeoutSec: 5`?** The hook is milliseconds-fast and purely local; 5s is ample and keeps the fail-open window negligible.

## Limitations

1. **`sessionStart` output shape is pattern-documented, not explicitly schema-documented.** The CLI does not clearly document the exact `additionalContext` output JSON shape for `sessionStart`; this package ships the top-level `{"additionalContext": "..."}` pattern that matches the documented usage. This is **version-coupled** — re-verify against the references after Copilot CLI upgrades.
2. **The reminder is advisory only.** It nudges the agent to use the skill; it cannot force a handoff, and a blocked/hung hook is fail-open (the session continues). It is not a guarantee that a summary is produced.
3. **POSIX/WSL only.** No PowerShell; on native Windows the bash-only hook does not run.
4. **Timeout fail-open (5s).** On timeout the hook is killed and the session continues normally. Keep the script fast (it is, by design).
5. **Requires explicit deployment.** Cataloged here but inactive until copied/deployed (see Install / Copy Paths).

## Uninstall

1. Delete the Copilot working-copy hook config and its script (using the actual shipped filenames):
   ```bash
   rm -f .github/hooks/completion-reminder.json .github/hooks/completion-reminder.sh
   rm -f ~/.copilot/hooks/completion-reminder.json ~/.copilot/hooks/completion-reminder.sh
   # if COPILOT_HOME is set:
   rm -f "$COPILOT_HOME/hooks/completion-reminder.json" "$COPILOT_HOME/hooks/completion-reminder.sh"
   ```
2. Delete the skill:
   ```bash
   rm -rf ~/.copilot/skills/work-completion-summary/
   rm -rf .github/skills/work-completion-summary/   # if a repo-local copy exists
   ```
3. Remove the package subtree if no longer wanted.
4. Restart the CLI so the registry reloads and no hooks/skills remain loaded.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Hook never fires | Missing `version: 1`; wrong location | Confirm `"version": 1`; `.github/hooks/completion-reminder.json` or absolute-path user-level copy |
| User-level hook fails to find script | Copied config with shipped relative `./completion-reminder.sh` + `cwd: ".github/hooks"` to `~/.copilot/hooks/` | Edit the JSON to an **absolute** script path and drop/absolutize `cwd` (or deploy repo-locally only) |
| Hook times out | Script too slow/hanging; `timeoutSec` too low | Speed up the script; this package's script is constant-output and milliseconds-fast |
| Reminder absent at session start | Fail-open timeout, or hook not deployed/registered | Confirm deployment path; the reminder is advisory — a missed nudge does not block the session |
| Skill not found by Copilot | Wrong destination or case | Confirm `~/.copilot/skills/work-completion-summary/SKILL.md` exact case; restart session |
| `/work-completion-summary` not listed | Skill registry not refreshed | Restart the `copilot` session or run `/skills reload`; `/skills list` to confirm |
| Behavior differs after upgrade | `sessionStart` output shape version-dependent | Re-verify against references; check `copilot --version` |

## Authoritative References

- GitHub Docs — *GitHub Copilot hooks reference* (hook schema, `sessionStart`, fail-open/fail-closed semantics): <https://docs.github.com/en/copilot/reference/hooks-reference>
- GitHub Docs — *Add agent skills and custom commands to your Copilot CLI* (skill discovery, `SKILL.md`, slash-invocation): <https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-skills>
- GitHub Docs — *Apply an IDE custom prompt with a prompt file* (prompt files are IDE-only, not supported in CLI): <https://docs.github.com/en/copilot/tutorials/customization-library/prompt-files>
- Agent Skills — format specification (frontmatter, `SKILL.md`, description hard cap): <https://agentskills.io/specification>
- GitHub Docs — *Add custom instructions to GitHub Copilot*: <https://docs.github.com/en/copilot/how-tos/copilot-cli/add-custom-instructions>

When in doubt, consult the references; this package is a summary, not a substitute for the source of truth.
