# ed3d-hook-jj-git-safety — Copilot CLI hook + Agent Skill

Safety guardrails for working with a protected jj + Git repository's version control from GitHub Copilot CLI: a `preToolUse` command hook that intercepts the `bash` tool, plus an Agent Skill (`skills/jj-git-safety/SKILL.md`) that encodes the jj/Git policy, checklist, remediation, and limits. It is **opinionated for protected jj + Git repositories**: it assumes the target repository is managed by Jujutsu (optionally colocated with Git) and treats direct Git mutation as unsafe.

> **This is a GitHub Copilot CLI package only.** It is not a Claude Code plugin, and Claude Code is not supported — the `preToolUse` hook and skill target the Copilot CLI v1 hook schema and payload/contract only. Do not try to register this package as a Claude Code plugin.

## Status: INACTIVE BY DEFAULT

**This package is inactive until explicitly activated.** The Copilot artifacts are **not deployed anywhere** — no hook file is installed into any target repo's `.github/hooks/` or `~/.copilot/hooks/`, and the skill is not copied into any skills directory. Installing or vendoring this package does **not** automatically deploy the hook or skill; treat the artifacts as documentation for opt-in activation.

| Aspect | Status |
|---|---|
| Copilot CLI hook installed | No (requires explicit copy/deployment) |
| Agent Skill installed | No (requires explicit skill installation/discovery) |
| Enforcement | Only after deployment |

## Layout

```
plugins/ed3d-hook-jj-git-safety/
├── README.md                            # this file
├── .claude-plugin/
│   └── plugin.json                      # catalog metadata (v1.1.0; Copilot-only)
├── hooks/
│   ├── jj-preflight.json                # Copilot CLI v1 preToolUse hook config (repo-local; matcher ^bash$, timeoutSec 5)
│   └── jj-preflight.sh                  # the enforcement script (POSIX sh; reads stdin JSON, emits stdout JSON)
├── skills/
│   └── jj-git-safety/
│       └── SKILL.md                     # the Agent Skill (policy, checklist, remediation, limits)
└── tests/
    ├── README.md                        # offline test-suite documentation
    ├── run-all.sh                       # runner over all suites
    ├── test-jj-preflight.sh             # exact contract + jj state matrix
    ├── test-scope.sh                    # scope boundaries / no-mutation / no-remote
    ├── test-package-layout.sh           # package layout / install-uninstall docs
    └── lib/                             # POSIX harness + offline, state-driven jj stub
```

`hooks/jj-preflight.json` is the **only** shipped runtime hook config — there is no `hooks.json`. The hook is a single Copilot CLI v1 `preToolUse` config plus its enforcement script.

## Install / Copy Paths

There are two artifacts to install: the **hook** (CLI enforcement) and the **skill** (agent-facing guidance). They install to different locations.

### 1. Copilot working-copy hook — copy path

Hooks are loaded from JSON files in a hooks directory. The shipped artifacts are `hooks/jj-preflight.json` (config) and `hooks/jj-preflight.sh` (the script). The config is **repo-local only as shipped**: it calls the script with a **relative** path (`./jj-preflight.sh`) and sets `cwd` to a **repo-root-relative** `.github/hooks`. Both paths resolve against the repository root, so this config works only when both files live in `.github/hooks/` of the target repo.

- **Repo-level (the only deployable form as shipped):** copy both files into `.github/hooks/` of the target repository so the policy travels with the repo and is reviewable:
  ```bash
  cp plugins/ed3d-hook-jj-git-safety/hooks/jj-preflight.json .github/hooks/
  cp plugins/ed3d-hook-jj-git-safety/hooks/jj-preflight.sh  .github/hooks/
  ```
- **User-level (`~/.copilot/hooks/`) requires an absolute script path — not supported as shipped.** Because `./jj-preflight.sh` and `cwd: ".github/hooks"` are repo-relative, copying the config to `~/.copilot/hooks/jj-preflight.json` unchanged resolves the script against the wrong location and the hook fails. To install a user-level hook you must edit `jj-preflight.json` so the `bash` field is an **absolute path** to `jj-preflight.sh` (and either remove `cwd` or set it to the script's absolute directory):
  ```bash
  cp plugins/ed3d-hook-jj-git-safety/hooks/jj-preflight.sh ~/.copilot/hooks/
  cp plugins/ed3d-hook-jj-git-safety/hooks/jj-preflight.json ~/.copilot/hooks/
  # then edit ~/.copilot/hooks/jj-preflight.json: "bash": "/abs/path/to/jj-preflight.sh", drop "cwd"
  ```
  If `COPILOT_HOME` is set, use `$COPILOT_HOME/hooks/` instead of `~/.copilot/hooks/`. (Native Windows uses `%USERPROFILE%\.copilot\hooks\` — not supported by this bash-only hook.)
- The config file must be valid JSON with top-level `version` and `hooks` keys (schema below). The filename may be anything but must end in `.json`; the script path inside it is what matters.

### 2. Agent Skill — copy path

Copilot CLI discovers Agent Skills by name. Copy the whole `skills/jj-git-safety/` directory (the folder named `jj-git-safety` containing `SKILL.md`) to a skills location Copilot CLI scans.

- **User-level (recommended, available in every repo):**
  ```
  cp -r plugins/ed3d-hook-jj-git-safety/skills/jj-git-safety ~/.copilot/skills/
  ```
  → `~/.copilot/skills/jj-git-safety/SKILL.md`
- **Repo-local (if Copilot CLI scans repo skills):** copy to `.github/skills/jj-git-safety/` in the target repository.
- **Verify:** the destination file must be named `SKILL.md` (exact case). Renaming to `skill.md` breaks discovery.
- After copying, restart the `copilot` session so the skill registry is refreshed.

## Copilot CLI v1 Hook Schema (exact)

One JSON object (this is exactly the shipped `hooks/jj-preflight.json`):

```json
{
  "version": 1,
  "hooks": {
    "preToolUse": [
      {
        "type": "command",
        "bash": "./jj-preflight.sh",
        "matcher": "^bash$",
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
| `type` | `"command"` | Command hook. (HTTP hooks exist but are always fail-open.) |
| `matcher` | `"^bash$"` | **Lowercase, anchored.** Regex against the runtime tool name. This package ships `"^bash$"` so it matches the lowercase runtime tool `bash` and nothing else. |
| `bash` | `"./jj-preflight.sh"` | Bash script for Linux/macOS/WSL. Relative here, so it resolves against `cwd` (repo-local). |
| `powershell` | (absent) | Deliberately omitted — POSIX/WSL only. On native Windows Copilot finds no `powershell` key and the hook does not run. |
| `cwd` | `".github/hooks"` | Working directory for the hook process (repo-root relative). Optional. |
| `timeoutSec` | `5` | Seconds before the hook is killed. This package ships **5 seconds**. |
| `env` | object | Optional extra env vars. Not used here. |

**Valid trigger keys:** `sessionStart`, `sessionEnd`, `userPromptSubmitted`, `preToolUse`, `postToolUse`, `errorOccurred` (plus `agentStop` on newer versions). This policy uses `preToolUse` only.

### preToolUse contract (what the script must do)

The hook script receives a single JSON object on **stdin**. The shipped `jj-preflight.sh` consumes this **top-level shape**:

```json
{
  "cwd": "/abs/path/to/repo-or-subdir",
  "toolName": "bash",
  "toolArgs": { ... } | "...serialized JSON string..." | [ ... ]
}
```

- `cwd` (string) — the authoritative working directory the command runs from.
- `toolName` (string) — the runtime tool name; only `bash` is inspected, everything else passes.
- `toolArgs` — the tool input. `jj-preflight.sh` accepts any of three forms: an **object** (e.g. `{"command":"git status"}`), a **serialized JSON string** (e.g. `"{\"command\":\"git status\"}"`), or an **array** of argv tokens (e.g. `["-c","git status"]`).

The script always emits an **exact** JSON object on stdout: `{"permissionDecision": "allow"}` or `{"permissionDecision": "deny", "permissionDecisionReason": "jj-preflight: ..."}`.

- `permissionDecision`: `"allow"`, `"deny"`, or `"ask"`; `permissionDecisionReason` is required when denying. If any `preToolUse` hook returns `"deny"`, the tool is blocked.
- `permissionDecisionReason` comes from a **fixed, generic vocabulary** (the `R_*` strings in `jj-preflight.sh`) and **never echoes secrets, arguments, or command text**.
- **Exit `0`** = success (use stdout decision; empty stdout → default/allow). **Non-zero exit or crash = deny (fail-closed)**, even if stdout says `allow`. **Timeout = fail-open** — the process is killed and the tool proceeds through the normal permission flow (it is NOT denied). This package ships a 5s timeout.

## Enforcement behavior (what `jj-preflight.sh` actually does)

The hook is **deterministic and deny-first**. It reads a JSON payload and statically classifies the command text; it never executes the command and never contacts a remote. The full fixed-reason vocabulary in `jj-preflight.sh` is `R_MALFORMED`, `R_NON_REPO`, `R_GIT_MUTATE`, `R_UNSAFE_CMD`, `R_COMPOUND`, `R_CONFLICT`, `R_GIT_OP`, `R_DETACHED`, `R_METADATA`, and `R_JJ_TRACKED`.

- Only the **`bash`** tool is inspected (matcher `^bash$`).
- **No repo found:** pure read-only commands allowed; *any* `git`/`jj` command denied (`R_NON_REPO`).
- **Clean colocated jj+git repo:** read-only git (`status`/`log`/`diff`/`branch`/`tag`/…) allowed; every git **mutating/staging** command (`add`, `commit`, `reset`, `push`, `pull`, `checkout`, `switch`, `mv`, `rm`, …) denied (`R_GIT_MUTATE`); ordinary jj operations allowed.
- **Tracked / stageable `.jj` (`R_JJ_TRACKED`):** when jj internals are tracked in the git index or stageable (`.jj` not git-ignored), git staging/mutation is denied with `R_JJ_TRACKED`.
- **Unresolved conflicts** deny all git commands and all jj mutations (`R_CONFLICT`); **git operation in progress** denies git/jj mutations (`R_GIT_OP`); **detached working copy** blocks git/jj mutations (`R_DETACHED`); **unverifiable jj metadata** denies git read/mutate (`R_METADATA`).
- **`git push --force` / `-f`** denied outright (`R_GIT_MUTATE`). **Every `jj git <subcommand>`** (push incl. all force/target forms, fetch, import, export, remote, clone, init) denied (`R_GIT_MUTATE`) — only bare `jj git` is read-only. A justified force-with-lease recovery on your own revisions is a **manual/user-run** step.

## Limitations (exact)

1. **Timeout is fail-open (5s).** On timeout the hook is killed and the tool proceeds through the normal permission flow — it is **not denied**. Keep the script fast (milliseconds), or a timeout means no protection. (Copilot CLI default is 30s; this package ships 5.)
2. **`preToolUse` non-timeout errors are fail-closed.** A crash or non-zero exit (other than a timeout) denies the tool call, which can block legitimate work; exit codes must be intentional.
3. **HTTP hooks and most non-`preToolUse` events are fail-open.** Enforcement relies on the `preToolUse` command hook only.
4. **No fine-grained `jj git` reasoning — but the whole family is blocked.** The hook denies **every** `jj git <subcommand>` with `R_GIT_MUTATE`; it does not whitelist any push/target/force form.
5. **Not a sandbox.** Advisory to the agent and best-effort at the hook layer; cannot stop the user's own shell, editor, sync, or a malicious agent.
6. **Matcher scope.** Intercepts only the `bash` tool; not `edit`/`write`/`Read`, subprocesses spawned from other tools, or commands issued outside the matched tool.
7. **POSIX/WSL only.** No PowerShell; on native Windows the bash-only hook does not run.
8. **No VCS-based protection for untracked files.** Untracked content is outside jj/Git recovery.
9. **Lexical command scanning.** The scanner is not shell-parser-aware: newline/CR separators, `;`, `&&`/`||`, command/process substitution, and write or read/write redirections (`>`/`<>`) are rejected from raw command text even when quoted. Read-only pipelines and input redirection (`<`) are permitted when otherwise classifiable; use one simple command per hook invocation.
10. **Version-coupled behavior.** Hook schema, matcher anchoring, and fail-open/fail-closed semantics depend on the Copilot CLI version. Re-verify against the references after upgrades.

## Uninstall

1. Delete the Copilot working-copy hook config and its script (using the actual shipped filenames):
   ```bash
   rm -f .github/hooks/jj-preflight.json .github/hooks/jj-preflight.sh
   rm -f ~/.copilot/hooks/jj-preflight.json ~/.copilot/hooks/jj-preflight.sh
   # if COPILOT_HOME is set:
   rm -f "$COPILOT_HOME/hooks/jj-preflight.json" "$COPILOT_HOME/hooks/jj-preflight.sh"
   ```
2. Delete the skill:
   ```bash
   rm -rf ~/.copilot/skills/jj-git-safety/
   rm -rf .github/skills/jj-git-safety/   # if a repo-local copy exists
   ```
3. Remove the package subtree if no longer wanted.
4. Restart the CLI so the registry reloads and no hooks/skills remain loaded.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Hook never fires | Missing `version: 1`; wrong location; matcher case | Confirm `"version": 1`; `.github/hooks/jj-preflight.json` or absolute-path user-level copy; use lowercase anchored `"^bash$"` with camelCase `preToolUse` |
| User-level hook fails to find script | Copied `jj-preflight.json` with shipped relative `./jj-preflight.sh` + `cwd: ".github/hooks"` to `~/.copilot/hooks/` | Edit the JSON to an **absolute** script path and drop/absolutize `cwd` (or deploy repo-locally only) |
| Matcher matches nothing | Used `"Bash"` (PascalCase) with camelCase `preToolUse`, or over-anchored regex | Use `"^bash$"`; recall the matcher is anchored `^(?:PATTERN)$` |
| Hook times out | Script too slow/hanging; `timeoutSec` too low | Speed up the script, remove blocking calls. This package ships `timeoutSec: 5`; raising it only widens the fail-open window |
| Tool ran anyway on timeout | Timeout is fail-open by design | Shrink runtime; treat timeout as "no protection", not "deny" |
| Legitimate command blocked | `preToolUse` non-zero exit = fail-closed deny | Fix script exit codes; `exit 0` with `allow`/no stdout for safe commands |
| A safe-looking multiline or quoted command is blocked | The scanner is lexical and rejects newlines and shell metacharacters even inside quotes | Split the work into one simple command per hook invocation |
| No effect on native Windows | bash-only hook, no `powershell` key | POSIX/WSL only by design; no fix |
| Skill not found by Copilot | Wrong destination or case | Confirm `~/.copilot/skills/jj-git-safety/SKILL.md` exact case; restart session |
| Behavior differs after upgrade | Schema/matcher semantics version-dependent | Re-verify against references; check `copilot --version` |

## Authoritative References

- GitHub Docs — *Using hooks with GitHub Copilot CLI* (v1 schema, file locations, `bash`/`powershell`, `timeoutSec`): <https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/use-hooks>
- GitHub Docs — *GitHub Copilot hooks reference* (matcher anchoring, `timeoutSec`/`timeout`, fail-open vs fail-closed, `preToolUse` semantics): <https://docs.github.com/en/copilot/reference/hooks-reference>
- Jujutsu VCS — official documentation (operation log, `jj op undo`, undo): <https://jj-vcs.dev/docs/>
- Git — `git-reflog`: <https://git-scm.com/docs/git-reflog>; `git-push` (`--force-with-lease`): <https://git-scm.com/docs/git-push>
- Agent Skills — format specification (frontmatter, `SKILL.md`): <https://agentskills.io/skills>

When in doubt, consult the references; this package is a summary, not a substitute for the source of truth.
