---
name: jj-git-safety
description: Enforce the jj/Git safety policy for this repository before and after version-control mutations. Invoke automatically before running jj or git commands that change repository state (commits, rebases, pushes, abandons, resets, cleanups, force pushes). Run on POSIX shells on Linux, macOS, and WSL only; no PowerShell support.
user-invocable: false
---

# jj-git-safety

Safety guardrails for working with the version control of a protected repository (a [Jujutsu](https://jj-vcs.dev/docs/) repo with a Git remote, possibly colocated with Git). This skill defines the jj/Git safety policy, a pre-mutation checklist, remediation steps, limits of the protection, and the authoritative references. Treat it as the agent-facing counterpart to the companion `preToolUse` hook described in this package's `README.md`.

> This skill is **opinionated for protected jj + Git repositories**. The Copilot artifacts are inactive until explicitly deployed. See the `README.md` for exact install, copy, schema, and limitation details.

## Scope

- **Supported environment:** POSIX shells (`bash`/`sh`) on Linux, macOS, and Windows Subsystem for Linux (WSL).
- **Not supported:** PowerShell, cmd.exe, or native Windows without WSL. The companion hook (`hooks/jj-preflight.sh` + `hooks/jj-preflight.json`, matcher `^bash$`, `timeoutSec: 5`) ships `bash` only and deliberately has no `powershell` key, so it never runs on native Windows.
- **Repositories in scope:** the protected jj repo this skill governs and any Git repo the agent is asked to mutate while this policy is active.
- **Command surface:** all jj/git writes — commits, amends, rebases, squashes, abandon/copy, push (incl. force), pulls, resets, checkouts/switches that move work, and destructive cleanups. Read-only commands (status, diff, log, show) are always safe and need only the "right repo" check.

## Safety Policy (jj and Git)

### jj (Jujutsu)

1. **Non-destructive by design.** Every operation is written to the operation log and is undoable with `jj op undo` (roll back the last operation), `jj op restore <id>` (roll back to a specific operation), or `jj undo` (restore the previous working-copy state). Prefer jj over Git for history rewriting.
2. **Auto-snapshot.** The working copy is snapshotted automatically before operations, so a mutated working-copy state has a recovery point.
3. **Never** `jj git push --force` on shared branches. A `jj git push -r <rev> --force-with-lease` on your own feature revisions (after reviewing the exact diff) is acceptable only as a **manual user action**: the companion hook denies the agent every `jj git push` form (`R_GIT_MUTATE`), so enforce force-push discipline here at the policy layer and have the user run any justified force-with-lease push outside the blocked agent hook path.
4. **Never `jj abandon` a revision you have not reviewed.** `jj abandon` is recoverable via `jj op undo` or `jj new <hash>`, but the revision leaves the default view — recover it before continuing rather than rebuilding from memory.
5. **Inspect before mutating.** Use `jj diff`, `jj log`, and `--dry-run`/`-n` where available to confirm exactly which revisions and files a command touches.
6. **Colocated caveat.** If the repo is colocated with Git, `jj` and `git` share the working copy. Do not run Git mutations directly on such a checkout unless you know the interaction.

### Git

1. **Never** `git reset --hard`. It discards uncommitted working-copy changes with no recovery path.
2. **Never** `git clean -fd` / `git clean -fdx`. It deletes untracked files that version control cannot restore.
3. **Never** `git push --force`. If a force push is ever justified, use `git push --force-with-lease` and only on your own branch.
4. **Avoid** `git checkout -- <path>` / `git restore <path>` on files with unsaved changes; review the diff first.
5. **Never** run `git checkout <branch>` / `git switch` while there is uncommitted work you care about without confirming it is safe (stash first if needed).
6. **Confirm before mutating.** Use `git status` and `git diff` to enumerate exactly what a command will change before running it.

### Protected-repository rules

1. **Never rewrite or force-push shared history.** Treat any branch others may have based work on as append-only from your side; route justified force-with-lease pushes to the user as a manual step.
2. **Never let VCS mutations touch content that version control does not track.** Verify the untracked set (`git status --porcelain`) before any destructive clean or reset so untracked work is never silently destroyed.
3. **Every significant VCS mutation belongs to a reviewed, coherent operation.** Prefer a single well-understood jj operation (recoverable via the op log) over scattered out-of-process commits or resets.
4. **Never commit secrets** — `.env`, keys, session artifacts, or tool-internal state. Consult `.gitignore` before staging and never stage VCS-internal directories (e.g. a tracked `.jj/`).

## Pre-Mutation Checklist

Run this checklist in order before *any* jj or Git command that writes history or the working copy. If any check fails, stop and remediate (next section).

- [ ] **Repo identity** — confirm I am in the intended repository (`jj root` / `git rev-parse --show-toplevel`). Never mutate the wrong checkout.
- [ ] **State snapshot** — `jj st` / `git status`: note modified and untracked files before touching anything.
- [ ] **No untracked surprises** — `git status --porcelain`: untracked files are expected, or `git clean` will not be used.
- [ ] **No protected-untracked content** — none of the files in scope live outside version-control tracking that a destructive command would wipe.
- [ ] **Target review** — for any force push / abandon / reset / rebase, I have reviewed the exact revision set (`jj log`, `jj diff`, `git log --oneline`).
- [ ] **No secrets** — no `.env`, key material, or session artifacts are among staged/pushed files.
- [ ] **Dry-run used where available** — the command supports `--dry-run`/`-n` (e.g. `git push --dry-run`) and I have run it.
- [ ] **Recovery path identified** — I know the undo command before mutating (`jj op undo`, `jj undo`, `git reflog`).
- [ ] **Working copy safe** — if using Git, no unrelated uncommitted work can be clobbered.

For **read-only** commands (status, diff, log, show), the checklist reduces to the "right repo" check; the rest does not apply.

## Remediation

When something goes wrong, follow these in order. Stop, do not stack more mutations.

1. **Stop.** Run no further VCS commands until the state is understood. `jj st` and `git status` are read-only and safe.
2. **jj recovery (operation log).** `jj op log` to inspect recent operations; `jj op undo` to roll back the last operation or `jj op restore <id>` to roll back to a specific one. The auto-snapshot means `jj undo` restores the prior working-copy state.
3. **Git recovery (reflog).** `git reflog` to find the pre-mutation commit, then inspect it with `git switch -c recovery/<timestamp> <commit>` before any reset. Only `git reset --hard` after confirming the working copy holds nothing of value (per the checklist it should not).
4. **Abandoned revisions.** `jj op undo` first. If the operation is gone, find the abandoned rev hash (`jj op log`) and `jj new <hash>` to bring it back. Do not recreate work from memory.
5. **Push gone wrong.** For a wrong or over-forced push, use `git reflog` / `jj op log` to find the original revision and restore it locally. Pushing it back with `--force-with-lease` is a **manual user-run step**: the hook denies the agent every `jj git push` / `git push` form, so you cannot perform it through the bash tool. Prepare the exact command and hand it to the user (or let them run it with the hook temporarily disabled). If the branch is shared and history was rewritten, stop and notify the user — do not silently fight concurrent changes.
6. **Accidental deletion of untracked content.** Stop immediately — untracked files are in neither jj's snapshot nor Git's reflog. Check the trash/recycle bin and editor backups. Run no further commands that write.
7. **After recovery.** Verify with `jj st` / `git status`, resume the workflow, and record what happened so the incident informs the operation going forward.

## Enforcement (what the companion hook actually blocks)

The companion `preToolUse` hook (`hooks/jj-preflight.sh`) is **deterministic and deny-first**; it statically classifies the command and never executes it. It intercepts only the `bash` tool (matcher `^bash$`); every other tool passes through. All deny reasons come from a fixed `jj-preflight: ...` vocabulary and never echo secrets, arguments, or command text. The full fixed-reason vocabulary is `R_MALFORMED`, `R_NON_REPO`, `R_GIT_MUTATE`, `R_UNSAFE_CMD`, `R_COMPOUND`, `R_CONFLICT`, `R_GIT_OP`, `R_DETACHED`, `R_METADATA`, and `R_JJ_TRACKED`.

**Normal protections (verified by the offline test suite):**

- **No repo found** (walk up from `cwd` for `.jj`/`.git`): read-only commands allowed; any `git`/`jj` command denied (`R_NON_REPO`).
- **Clean colocated jj+git repo, attached bookmark:** read-only git (`status`/`log`/`diff`/`branch`/`tag`/…) allowed; every git mutating/staging command (`add`, `commit`, `reset`, `push`, `pull`, `checkout`, `switch`, `mv`, `rm`, …) denied (`R_GIT_MUTATE`); ordinary jj operations allowed.
- **Tracked / stageable `.jj` (`R_JJ_TRACKED`):** when `.jj` internals are tracked in the git index or stageable (not git-ignored), all git staging/mutation is denied with `R_JJ_TRACKED` (no per-path carve-out) — `git add .jj/...`, `git add -A`, `git add .`, `git add -u`, `git rm <tracked .jj>`, and broad `git add` while `.jj` is not ignored. When `.jj` is not tracked/stageable, generic git mutation is denied with `R_GIT_MUTATE`.
- **Unresolved conflicts** (`jj log -r 'conflicts()'` non-empty): denies all git commands (incl. read-only `git status`) and all jj mutations; jj read-only still allowed (`R_CONFLICT`).
- **Git operation in progress** (`.git/` markers like `MERGE_HEAD`, `index.lock`, …): denies git and jj mutations (`R_GIT_OP`); jj read-only allowed.
- **Detached working copy** (no bookmark on `@`): read-only allowed; any git/jj mutation denied (`R_DETACHED`). Because bookmark-writes (`jj bookmark create/move`) count as jj mutations, attaching a bookmark to a detached `@` is also blocked. Do not work around by forcing the hook aside — resolve the detached state via the normal permission flow, temporarily disabling the hook, or manual user action.
- **Unverifiable jj metadata/root** (e.g. `jj`/`jq` unavailable, or `jj root` disagrees with the discovered root): git read-only in a jj repo and git mutations denied (`R_METADATA`); non-mutating jj allowed.
- **Malformed input**, missing `cwd`/`toolName`, and empty command → denied (`R_MALFORMED`, fail-closed).
- **No remote hook calls:** the hook is fully offline and never contacts or mutates a remote.

**Force-push / target / outgoing behavior:**

- **`git push --force` / `git push -f`** are denied outright as git mutations (`R_GIT_MUTATE`) in a jj-managed repo.
- **Every `jj git <subcommand>` is denied** with the fixed reason `R_GIT_MUTATE` — the hook does not do fine-grained target/force parsing, but its coarse `jj git` family classification blocks all of `jj git push` (default, `-r`, `--from`/`--to`, `--to`, `--force`, `--force-with-lease`), `jj git fetch`, `jj git import`, `jj git export`, `jj git remote`, `jj git clone`, and `jj git init`. No `jj git` form passes even in a clean, attached, conflict-free, verifiable repo. (A more specific state reason — e.g. `R_JJ_TRACKED` when `.jj` is tracked — can precede `R_GIT_MUTATE`, but never allows the command.)
- Only bare `jj git` (prints help) is treated as read-only.

Consequence: **jj force-push and push-target discipline are enforced at the hook level** (the agent cannot run any `jj git` command at all), while the *policy* layer in this skill governs what the **user** may run manually. The agent must route any justified force-with-lease push to the user as a manual step (see Remediation); the hook will block the agent from doing it.

**Timeout fail-open:** the hook ships `timeoutSec: 5`. On timeout it is killed and the tool proceeds through the normal permission flow — it is **not denied**. Keep hook script runtime far under 5s.

## Limits (what this protection does NOT cover)

1. **Timeout is fail-open (5s).** The companion hook ships `timeoutSec: 5`; on timeout the hook process is killed and execution **continues through the normal permission flow** — the tool is **not denied**. A slow or hanging hook provides no protection. Keep hook scripts fast and side-effect-free. (The Copilot CLI default is 30s, but this package ships 5.)
2. **No fine-grained `jj git` reasoning — but all `jj git` is blocked.** The hook does not parse `jj git push` force/`--force-with-lease`, targets, or outgoing sets for a *specific* reason; instead it denies **every** `jj git <subcommand>` with `R_GIT_MUTATE` (a state reason like `R_JJ_TRACKED` may precede it). No `jj git` push/target/force form passes. `git push --force`/`-f` is still denied.
3. **`preToolUse` non-timeout errors are fail-closed.** A crash or non-zero exit (other than a timeout) denies the tool call, which can block legitimate work. Exit codes must be intentional.
4. **HTTP hooks and most non-`preToolUse` events are fail-open.** This skill relies on a command hook; it cannot protect events it is not registered for (`sessionStart`, `postToolUse`, `errorOccurred`, etc. are not enforcement points).
5. **Not a sandbox.** The policy is advisory to the agent and best-effort at the CLI hook layer. It cannot stop the user's own terminal commands, editor operations, sync processes, or a deliberately malicious agent.
6. **Matcher scope.** The hook only intercepts the tool whose runtime name matches (`bash`). It does not intercept `edit`/`write`/`Read` tools, subprocesses spawned from other tools, or commands issued outside the matched tool.
7. **POSIX/WSL only.** No PowerShell support; on native Windows the bash-only hook will not run.
8. **No guarantee against data loss.** Untracked files, editor state, and anything deleted outside VCS are outside VCS recovery.
9. **Lexical command scanning.** The scanner is not shell-parser-aware: newline/CR separators, `;`, `&&`/`||`, command/process substitution, and write or read/write redirections (`>`/`<>`) are rejected from raw command text even when quoted. Read-only pipelines and input redirection (`<`) are permitted when otherwise classifiable; use one simple command per hook invocation.
10. **Behavior drift.** Hook schema, matcher semantics, and fail-open/fail-closed behavior are tied to the installed Copilot CLI version. Re-verify against the references after upgrades.

## Authoritative References

- GitHub Docs — *Using hooks with GitHub Copilot CLI* (v1 schema, file locations, `bash`/`powershell`, `timeoutSec`): <https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/use-hooks>
- GitHub Docs — *GitHub Copilot hooks reference* (matcher anchoring, `timeoutSec`/`timeout`, fail-open vs fail-closed, `preToolUse` semantics): <https://docs.github.com/en/copilot/reference/hooks-reference>
- Jujutsu VCS — official documentation (operation log, `jj op undo`, undo): <https://jj-vcs.dev/docs/>
- Git — `git-reflog`: <https://git-scm.com/docs/git-reflog>; `git-push` (`--force-with-lease`): <https://git-scm.com/docs/git-push>
- Agent Skills — format specification (frontmatter, `SKILL.md`): <https://agentskills.io/skills>

When in doubt, consult the references; this skill is a summary, not a substitute for the source of truth.
