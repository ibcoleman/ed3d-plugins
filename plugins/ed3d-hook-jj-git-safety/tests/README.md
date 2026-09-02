# jj-git-safety test suite

Fully **offline** verification of the **Copilot CLI-only** `jj-git-safety`
`preToolUse` hook (`plugins/ed3d-hook-jj-git-safety/hooks/jj-preflight.sh`) and its package docs.

Tests are POSIX shell, run in `mktemp` sandboxes, and exercise the **real hook**
against a state-driven `jj` stub plus the local, offline `jq` binary. No remote
is contacted and **nothing outside the sandbox is mutated**.

## Run

```
./run-all.sh
# or individually:
sh test-jj-preflight.sh
sh test-scope.sh
sh test-package-layout.sh
```

Each suite prints a TAP-like `ok`/`not ok`/`skip` report and a final count, and
exits non-zero if any assertion fails. The current suite totals are 33 scope,
56 package-layout, and 332 preflight assertions (421 total).

## Layout

```
tests/
├── run-all.sh                # runner over all three suites
├── test-jj-preflight.sh      # exact preToolUse contract + jj states + tools
├── test-scope.sh             # scope boundaries + no-mutation + no-remote
├── test-package-layout.sh    # package layout / hook / skill / docs
└── lib/
    ├── harness.sh            # shared POSIX helpers, payload builders, PATHs
    ├── fixtures/
    │   └── indexed-jj-repo.sh # genuine git index fixture with tracked .jj state
    └── stubbin/
        └── jj                # state-driven offline jj stub (root/conflicts/bookmark)
```

The `jj` stub is a real-jj-compatible simulation: it honors the `-T <template>`
the hook passes to `jj log`, prints the template once per matched rev, and
models exit status (a `JJ_STUB_<SUB>_FAIL=1` flag makes a subcommand fail like
a broken `jj`). With `JJ_STUB_REMOTE=1` it also flags any non-query invocation
as `REMOTE-CALLED`, proving the hook never delegates network/remote work to jj.

The hook under test is resolved to `plugins/ed3d-hook-jj-git-safety/hooks/jj-preflight.sh`
(override with `JJ_GIT_SAFETY_HOOK`).

## What is covered

- **Exact contract**: stdout JSON `{"permissionDecision","permissionDecisionReason"}`;
  `allow` (no reason) vs `deny` (required reason); hook always exits `0` on a
  handled decision; non-bash tools pass through.
- **Allow / deny matrix** (validated empirically against the real hook):
  - non-repo: pure read-only allowed; any git/jj command → `R_NON_REPO`
  - clean colocated jj+git: read-only git allowed; `git add/commit/reset/push/
    checkout/mv/rm` → `R_GIT_MUTATE`; jj operations allowed when clean
  - jj states: unresolved conflicts → `R_CONFLICT`; git op marker
    (`MERGE_HEAD`, `index.lock`, …) → `R_GIT_OP`; detached working copy →
    `R_DETACHED`; unverifiable jj root/target → `R_METADATA`
- **Explicit/broad adds**: `git add .jj/...`, `git add -A`, `git add .` all denied.
- **copy/rename/archive/extraction**: `git mv` → `R_GIT_MUTATE`; `cp`/`mv`/
  `tar`/`unzip`/`curl` → `R_UNSAFE_CMD`.
- **Compound/wrappers/redirection**: `&&` `;` pipelines, `$( )`, backticks,
  `sudo`/`eval`/`xargs`/`env`/`nohup`/`setsid`, write `>` and read/write `<>` → `R_COMPOUND`; these checks are lexical rather than quote-aware. Read-only pipelines and input redirection (`<`) remain allowed when otherwise classifiable.
- **Tool availability**: jq missing → `R_MALFORMED` (fail-closed); jj missing →
  `R_METADATA` for git mutations, read-only jj still allowed. These tests are
  hermetic: they run under a minimal, fully-controlled PATH (only the resolved
  coretools the hook needs, with no `/usr/bin:/bin` fallback) and assert the
  tool is genuinely absent on that PATH before exercising the hook.
- **Malformed/redaction**: empty/invalid payloads, missing fields, empty command
  → `R_MALFORMED`; deny reasons come from a fixed vocabulary and never echo
  secrets, tokens, or command text.
- **Input forms**: object, serialized-string, and array `toolArgs` all parsed.
- **Regression nets**: `command`/`builtin`/`type` wrappers, process
  substitution `<( )`/`>( )`, newline separators, unsafe git `branch`/`tag`/
  `config`/`remote` mutations, jj post-mutation ops (`jj op undo`, `jj file
  untrack`, `jj util`/`debug`, `jj git remote add`/`clone`/`init`), every
  `jj git push` force/ambiguous-target form, direct git force-push forms, and
  staged/tracked `.jj` + git index mutations. These assert the INTENDED FINAL
  CONTRACT (denial) and the suite is green against the hardened hook.
- **Every git/jj occurrence + pipeline bypasses**: a multi-invocation pipeline
  (`git status | git checkout main`, `git diff | git apply --index`,
  `git log | git branch -D x`, `jj log | jj git push --force`) is denied as
  R_COMPOUND (the every-occurrence guard); a single write hidden behind a
  leading non-git verb (`cat f | git add -`) or a jj global option
  (`jj -R path git push`) is still classified as the mutating op it is →
  R_GIT_MUTATE; read-only single-occurrence pipelines stay allowed.
- **jj global options carrying a value** (`--at-op <op>`, `--config <k>=<v>`):
  a mutating `jj git push` / `jj git fetch` placed behind such a value-carrying
  global option is still classified as the mutating op it is → R_GIT_MUTATE
  (the value after a global option is not the subcommand); object, serialized
  string, and array toolArgs forms are all covered, and the read-only negative
  control `jj --at-op abc log` stays allowed.
- **R_JJ_TRACKED with a real indexed-`.jj` fixture**: the fixture script
  `lib/fixtures/indexed-jj-repo.sh` builds a genuine git index tracking a
  `.jj/` path, so the hook's read-only index inspection genuinely fires.
  Mutating/staging git ops and jj writes on such a repo → R_JJ_TRACKED, while
  read-only git/jj stays allowed; the R_JJ_TRACKED vocabulary string is pinned
  against the packaged hook.
- **jj conflict-stub modeling**: the stub records the exact `-T` template the
  hook passes to `jj log` (guarded to the valid real-jj `-T description` form,
  not `-T x`) and models failure statuses (`JJ_STUB_ROOT_FAIL` /
  `JJ_STUB_LOG_FAIL` / `JJ_STUB_BOOKMARK_FAIL`).
- **jj exit-status simulation**: a failing `jj root` → `R_METADATA`; a failing
  conflict query with a clean root still allows read-only git.
- **Scope**: only `bash` intercepted; nested cwd repo discovery (walk up);
  non-repo handled; no repository mutation; no remote traffic (stub's
  `REMOTE-CALLED` guard proves the hook never asks jj for a network op).
- **Package**: real files present, POSIX hook with fixed reason vocabulary,
  valid v1 hook JSON (`matcher: "^bash$"`, type `command`, `timeoutSec: 5`),
  Copilot-only layout (no Claude hook manifest), skill frontmatter/sections,
  README install/uninstall/status docs.

## Testing a custom hook build

```
JJ_GIT_SAFETY_HOOK=/abs/path/to/jj-preflight.sh ./run-all.sh
```
