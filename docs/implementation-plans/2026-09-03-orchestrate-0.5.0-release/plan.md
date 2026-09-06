# ed3d-orchestrate 0.5.0 — Enforcement Branch B (amended scope)

## Goal

Ship the **amended** `ed3d-orchestrate` 0.5.0 release: the plan-review → builder
handoff gate is **protocol-only** (**Branch B**), and the release documentation
corrects the earlier traceability finding that `ed3d-orchestrate`'s live
dependency on `ed3d-plan-and-execute` extends to all four builder/fixer agents.
In fact `ed3d-orchestrate` dispatches exactly two of them.

This is a documentation/traceability release, not a behavioral one. It changes
no hook and adds no builder-gate artifact or registration. The Branch B decision
itself is unchanged from the shipped 0.5.0; this plan records the corrected
scope and makes the dependency claim accurate and test-backed.

## Implementation Summary

- Correct the runtime-dependency claim so only `task-implementor-fast` (Phase 4
  builder fanout) and `task-bug-fixer` (adversarial-review fix loop) are
  described as `ed3d-orchestrate` dependencies of `ed3d-plan-and-execute`.
- Explain that `code-reviewer` and `test-analyst` remain because the **frozen
  legacy package** still dispatches them in its own planning/execution workflow,
  and the **repository validator**'s expected-twins set still lists them — not
  because `ed3d-orchestrate` dispatches them.
- Add `/how-to-customize` to every frozen command list so all five deprecated
  commands are named consistently.
- Check in this release plan (plan.md-only) recording the amended Branch B scope
  and pointing to the evidence artifact and the enforcing tests.
- Leave `hooks.json` and both existing hook scripts unchanged.

## Implementation Plan

### Phase 1 — Correct the runtime-dependency traceability

1. `plugins/ed3d-plan-and-execute/README.md`: rewrite the "Not deprecated — still
   a live dependency" block so `task-implementor-fast` and `task-bug-fixer` are
   the `ed3d-orchestrate` runtime dependencies, and `code-reviewer` /
   `test-analyst` remain for frozen legacy package/validator compatibility, not
   orchestrate dispatch.
2. `CHANGELOG.md` (top `[ed3d-orchestrate] [0.5.0]` entry): apply the same
   corrected wording to the "builder/fixer agents" bullet.
3. `ROADMAP.md` (0.5.0 landed entry): apply the same corrected wording so the
   roadmap does not repeat the stale four-agent enumeration.

### Phase 2 — Frozen command list consistency

4. Add `/how-to-customize` to the frozen planning-command list in the root
   `README.md` and in `plugins/ed3d-00-getting-started/commands/getting-started.md`
   so all five deprecated commands are named consistently with
   `plugins/ed3d-plan-and-execute/README.md`.

### Phase 3 — Release plan artifact

5. Check in this plan at
   `docs/implementation-plans/2026-09-03-orchestrate-0.5.0-release/plan.md`.
   It is the **only** top-level artifact in its directory (plan.md-only
   contract). It records the amended Branch B scope and points to the evidence
   and enforcing tests (see Test Strategy).

No hook file, hook registration, or builder-gate artifact is introduced or
modified.

## Acceptance Criteria

- **AC.1:** `plugins/ed3d-plan-and-execute/README.md` names only
  `task-implementor-fast` and `task-bug-fixer` as `ed3d-orchestrate` runtime
  dependencies and explains that `code-reviewer` / `test-analyst` remain for
  frozen legacy package/validator compatibility, not orchestrate dispatch.
  Verified by reading the corrected block and by
  `python3 scripts/test_orchestrate_agent_dependencies.py` (which asserts the
  twin contract for exactly these two builders/fixers).
- **AC.2:** `CHANGELOG.md` and `ROADMAP.md` state the same corrected dependency
  claim. Verified by reading the corrected entries.
- **AC.3:** every frozen planning-command list (root `README.md`,
  `getting-started.md`, `plugins/ed3d-plan-and-execute/README.md`) includes
  `/how-to-customize`. Verified by grep across the three files.
- **AC.4:** a checked-in release plan exists at
  `docs/implementation-plans/2026-09-03-orchestrate-0.5.0-release/plan.md` and is
  the only top-level file in its directory. Verified by
  `python3 scripts/test_plan_artifact_contract.py`.
- **AC.5:** the Branch B contract (protocol-only; no builder-gate artifact or
  registration; no mechanical claims) still holds and is test-backed. Verified by
  `python3 scripts/test_orchestrate_enforcement_branch.py`.
- **AC.6:** no hook (`hooks.json`, `check-review-loop.py`,
  `adversary-write-guard.py`) was modified. Verified by
  `python3 scripts/test_context_handoff_scope.py <base-revision>` (protected-path
  rejection) and by inspection.

## Test Strategy

- **Dependency contract:** `python3 scripts/test_orchestrate_agent_dependencies.py`
  asserts the exact-twin contract for `task-implementor-fast` and
  `task-bug-fixer` — the two agents `ed3d-orchestrate` actually dispatches.
- **Plan.md-only contract:** `python3 scripts/test_plan_artifact_contract.py`
  asserts every plan directory under `docs/implementation-plans/` contains
  exactly one top-level `plan.md`.
- **Branch B contract:** `python3 scripts/test_orchestrate_enforcement_branch.py`
  asserts the evidence says protocol-only, there is no builder-gate
  artifact/registration, and no mechanical claims are made. Evidence artifact:
  `docs/research/2026-09-03-orchestrate-enforcement-branch-b.evidence.md`.
- **Scope contract:** `python3 scripts/test_context_handoff_scope.py <base-revision>`
  rejects any change outside the approved 0.5.0 release allowlist and any
  protected path (`hooks.json`, both hook scripts, facets/transclusion). Plan
  artifacts under `docs/implementation-plans/` are an allowed family.
- **Regression:** `python3 scripts/test-dispatch-protocol.py`,
  `python3 scripts/validate_plugins.py`, and the two hook suites remain green.
- **AC mapping:** AC.1→`test_orchestrate_agent_dependencies.py`; AC.2→inspection;
  AC.3→grep; AC.4→`test_plan_artifact_contract.py`; AC.5→
  `test_orchestrate_enforcement_branch.py`; AC.6→`test_context_handoff_scope.py`.

## Review Strategy

This is a documentation-only amendment to an already-released 0.5.0. Before
landing, the plan is reviewed against the evidence artifact and the enforcing
tests: confirm the runtime-dependency wording names exactly the two dispatched
agents, confirm the frozen command lists are consistent, and confirm no hook or
builder-gate artifact appears in the diff. The existing adversarial-review /
tumble-dryer workflow may be run against the committed range; any critical/high
finding is fixed and re-reviewed.

## Risks

- **Doc/dependency drift:** future wording could re-add `code-reviewer` /
  `test-analyst` as orchestrate dependencies or drop `/how-to-customize` from a
  frozen list. Mitigation: the corrected wording is in the authoritative plugin
  README and changelog, and the scope test bounds the release diff.
- **Branch B residual (unchanged):** the mechanical builder-gate follow-up
  (Branch A) remains deferred until a native builder-dispatch payload and
  identity are validated and evidenced on a current Copilot CLI. This release
  makes no mechanical claim; it only corrects documentation.
- **Validator coupling:** `code-reviewer` and `test-analyst` remain required by
  the frozen legacy package and the repository validator's expected-twins set,
  so they stay maintained even though `ed3d-orchestrate` does not dispatch them.
  This is intentional and documented, not an orchestrate dependency.
