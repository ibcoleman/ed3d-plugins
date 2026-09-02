# ed3d-completion-summary test suite

Fully **offline** verification of the **Copilot CLI-only** `ed3d-completion-summary`
package: its `sessionStart` command hook (`plugins/ed3d-completion-summary/hooks/completion-reminder.sh`)
and its package docs / layout.

Tests are POSIX shell, run in `mktemp` sandboxes, and exercise the **real hook**.
No remote is contacted and **nothing outside the sandbox is mutated**.

## Run

```
./run-all.sh
# or individually:
sh test-completion-reminder.sh
sh test-package-layout.sh
```

Each suite prints a TAP-like `ok`/`not ok`/`skip` report and a final count, and
exits non-zero if any assertion fails. The current suite totals are 27
completion-reminder and 42 package-layout assertions (69 total).

## Layout

```
tests/
├── run-all.sh                     # runner over both suites
├── test-completion-reminder.sh    # exact sessionStart output contract + scope
├── test-package-layout.sh         # package layout / skill / hook / docs
└── lib/
    └── harness.sh                 # shared POSIX helpers, sandbox, runner
```

The hook under test is resolved to `plugins/ed3d-completion-summary/hooks/completion-reminder.sh`
(override with `COMPLETION_REMINDER_HOOK`).

## What is covered

- **Exact contract**: the hook always emits the single constant
  `{"additionalContext": "..."}` line on stdout, byte-exact (single line with a
  pinned trailing newline), and exits `0`.
- **Input dialect/shape invariance**: valid camelCase `sessionStart` payload,
  VS Code snake_case payload, empty stdin, and binary-garbage stdin all yield
  the identical byte-exact output and exit `0` (deterministic constant output;
  the payload is ignored).
- **Determinism**: three runs produce identical bytes.
- **Scope / side effects**: running the hook in a pristine temp cwd creates no
  new files; the script references no network commands (`curl`/`wget`), no
  `git`/`jj`/`.git`/`.jj`, no `python`, and no `jq`; it parses cleanly under
  POSIX `dash` (and `sh`).
- **Package layout**: all required files exist; no Claude Code `hooks.json`
  ships; SKILL.md frontmatter `name` equals the directory name with a quoted,
  `<=1024`-char `description` and **no** `user-invocable` key; plugin.json has
  name/version `0.1.0`/`copilot-only`; `completion-reminder.json` is valid JSON
  with `version: 1`, **no** `matcher`, **no** `powershell`, and `timeoutSec: 5`;
  README documents install paths for both artifacts, the `additionalContext`
  output contract, and the version-coupled / under-documented limitation.

## Testing a custom hook build

```
COMPLETION_REMINDER_HOOK=/abs/path/to/completion-reminder.sh ./run-all.sh
```
