# ed3d-orchestrate Enforcement Branch — Branch B (protocol-only) Evidence

**Date:** 2026-09-03
**Target:** `ed3d-orchestrate` 0.5.0 handoff-gate enforcement decision
**Status:** Branch B — protocol-only. No mechanical builder-gate artifact, no registration, no mechanical claims.

## Validation limitation (Copilot CLI 1.0.82)

On Copilot CLI **1.0.82** we attempted to validate the native builder-dispatch
payload and agent identity that a mechanical builder-gate hook would need — a
`preToolUse` hook that blocks the first builder dispatch until an operator
approval is recorded in `.ed3d/orchestrate-state.json`.

That validation is **not conclusive on 1.0.82**. The official hook reference
documents `task` as a tool but does not specify an agent/resource identity in
the pre-tool payload, and this checkout has no captured builder-dispatch
fixture from a live run on 1.0.82. Without a validated payload and identity, a
mechanical matcher cannot be built safely; guessing at one risks blocking
legitimate builder dispatches — the same failure class the existing
`adversary-write-guard.py` already guards against. This validation limitation
is the reason the mechanical slice stays deferred.

## Decision: Branch B (protocol-only)

Given the 1.0.82 validation limitation, the plan-review → builder handoff gate
ships as **protocol-only** guidance (the mechanism already implemented in the
workflow text, tested by the context-handoff suites):

- **No builder-gate hook artifact** is added — there is no new `preToolUse`
  script (no `builder-gate.py` or equivalent) in
  `plugins/ed3d-orchestrate/hooks/`.
- **No builder-gate registration** is added to `hooks.json` — only the two
  existing hooks (`check-review-loop.py`, `adversary-write-guard.py`) remain
  registered.
- **No mechanical claims** are made: the handoff gate is **not mechanical** and
  is **not** native Copilot runtime enforcement. It remains prompt/protocol-only
  guidance; no mechanical or runtime enforcement claim is made for it.

Branch A (a mechanical builder-gate artifact plus `hooks.json` registration) is
**rejected** until a native builder-dispatch payload and identity are validated
and evidenced on a current Copilot CLI.

## Verification

`python3 scripts/test_orchestrate_enforcement_branch.py` asserts exactly this
Branch B contract: the evidence says protocol-only; no builder-gate artifact
exists; no builder-gate registration exists in `hooks.json`; and no mechanical
claims are made.
