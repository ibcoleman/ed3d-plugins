# Orchestrate Phase Plans Design

## Summary
<!-- TO BE GENERATED after body is written -->

## Definition of Done
- `ed3d-orchestrate` accepts the existing phase-directory implementation-plan format while retaining a reviewed top-level manifest and the mandatory operator approval checkpoint.
- After approval, execution loads one phase at a time, persists phase progress across `/clear` + resume, keeps the existing per-phase review/fix loop, and finishes with the adversarial review loop over the complete commit range.
- The change is Copilot-only, covered by deterministic offline tests plus a real local Copilot CLI workflow run, with documentation and version/catalog/changelog updates synchronized and a branch prepared for a PR to `ibcoleman/ed3d-plugins`.

This does not include maintaining new Claude Code behavior; existing Claude artifacts remain frozen legacy.

## Acceptance Criteria
<!-- TO BE GENERATED and validated before glossary -->

## Glossary
<!-- TO BE GENERATED after body is written -->
