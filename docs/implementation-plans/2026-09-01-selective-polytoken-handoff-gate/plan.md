# Selective Polytoken Port: Mechanical Operator Handoff Gate

## Goal

Add the smallest safe high-value Copilot CLI slice identified by the portability audit: strengthen and test the existing `ed3d-orchestrate` plan-review-to-builder operator handoff boundary. Preserve the existing plan-review gate, builder dispatch, adversarial-review loop, state protocol, and hooks without duplicating or changing their behavior.

The result is a selective, prompt/protocol-only port of Polytoken's explicit `handoff_plan` approval semantic. Copilot has no native facet/runtime approval primitive, and this checkout has no verified native builder-dispatch payload suitable for a new mechanical matcher. This slice therefore must not guess at a hook boundary. It improves the existing approval prompt and makes its ordering contract executable; a mechanical repository-hook backstop remains a separately deferred follow-up.

## Implementation Summary

Update the existing Context Handoff Gate prose in `orchestrating-the-loop/SKILL.md`, the command's handoff/resume wording where needed, and the README's capability/enforcement classification. Add named offline protocol and documentation-contract tests that assert the gate is armed in the documented state transition, the orchestrator stops before builders, explicit `continue`/resume approval precedes builder dispatch, and no claim of native runtime enforcement is made.

This slice is prompt-only guidance plus executable repository contract tests. It does not add a hook or state flag. Native Polytoken runtime enforcement is unavailable; repository hook/script enforcement is explicitly deferred because the exact Copilot native `task` delegation payload and builder identity are not evidenced. Existing repository hooks remain unchanged.

## Implementation Plan

### Phase 1 — Strengthen the existing prompt/protocol boundary

1. Update `plugins/ed3d-orchestrate/skills/orchestrating-the-loop/SKILL.md` only in the existing Context Handoff Gate and adjacent state-transition prose.
   - Make explicit that the plan-review pass is followed by an operator approval checkpoint, not merely a context-management suggestion.
   - Preserve the mandatory end-of-turn rule and the prohibition on builder dispatch in that turn.
   - Define `continue` and `/clear` + resume as the two approval paths, with builder dispatch allowed only after the approval response/resume has been processed.
   - Do not add `gate_pending` or alter review state semantics.
2. Update `plugins/ed3d-orchestrate/commands/orchestrate.md` only where needed to use the same unambiguous approval/resume terminology.
3. Update `plugins/ed3d-orchestrate/README.md` to identify the existing boundary as prompt-only guidance, state that native runtime enforcement is unavailable, and defer mechanical hook enforcement until native builder-dispatch identity is evidenced.

### Phase 2 — Add executable protocol and documentation contracts

1. Add `scripts/test_context_handoff_protocol.py` as a standalone offline test.
   - Read the actual skill and command files.
   - Assert the gate contains approval language, the mandatory stop/end-turn language, and the no-builder-in-that-turn invariant.
   - Assert the approval/resume wording precedes the first builder-dispatch instruction in the relevant source order.
   - Assert the existing state fields remain the documented fields and no speculative `gate_pending` hook contract is introduced.
2. Add `scripts/test_context_handoff_documentation.py` as a standalone offline test.
   - Assert the README and skill distinguish native runtime enforcement, prompt-only guidance, and deferred repository hook/script enforcement.
   - Assert the docs name the missing native builder-dispatch evidence as the prerequisite for a future mechanical slice.
   - Assert explicit deployment/version-drift limitations are not overstated for this prompt-only slice.
3. Add `scripts/test_context_handoff_scope.py <base-revision>` as a standalone zero-dependency scope test.
   - Validate that the supplied base revision exists.
   - Inspect the changed-path set from the supplied revision to the current checkout.
   - Allow only the three intended protocol/documentation files and the three new test files, plus any explicitly approved roadmap/changelog/version files if the implementation plan is amended to include them.
   - Reject changes to `hooks.json`, either existing hook script, facet/transclusion resources, unrelated plugins, and all other unexpected paths.
4. Keep existing `hooks.json`, `check-review-loop.py`, and `adversary-write-guard.py` unchanged; the scope test provides the path-level guarantee.

### Phase 3 — Integration verification

1. Run `python3 scripts/test_context_handoff_protocol.py` and `python3 scripts/test_context_handoff_documentation.py`.
2. Run `python3 plugins/ed3d-orchestrate/hooks/test-check-review-loop.py`, `python3 plugins/ed3d-orchestrate/hooks/test-adversary-write-guard.py`, `python3 scripts/test-dispatch-protocol.py`, and `python3 scripts/validate_plugins.py`.
3. Run `python3 scripts/test_context_handoff_scope.py <base-revision>` against the implementation range.
4. Inspect the final protocol wording and verify that existing hook files and review-window behavior were not changed; do not port facets, transclusion/Jinja, broad hook parity, researcher agents, or unrelated deferred follow-ups.

## Acceptance Criteria

- **AC.1:** After a clean plan-review result, the documented workflow presents an explicit operator approval checkpoint and forbids builder dispatch in that same turn. Verified by `python3 scripts/test_context_handoff_protocol.py`.
- **AC.2:** The documented `continue` and `/clear` + resume paths both require approval processing before the workflow begins builder dispatch. Verified by named ordering assertions in `scripts/test_context_handoff_protocol.py`.
- **AC.3:** Documentation accurately classifies the slice as prompt-only guidance, states that native Copilot runtime enforcement is unavailable, and defers repository hook/script enforcement pending verified native builder-dispatch evidence. Verified by `python3 scripts/test_context_handoff_documentation.py`.
- **AC.4:** This slice does not introduce a second plan-review/adversarial gate, `gate_pending`, or a new hook, and the existing hook files remain outside the implementation path set. Verified by explicit negative assertions in `scripts/test_context_handoff_protocol.py` and the path-level allowlist in `scripts/test_context_handoff_scope.py <base-revision>`; existing hook/dispatch suites provide behavioral regression coverage but are not claimed to prove source non-modification.
- **AC.5:** The implementation remains bounded to the handoff protocol/docs/tests and does not add facet/transclude/Jinja parity or unrelated plugin changes. Verified by `scripts/test_context_handoff_scope.py <base-revision>` against the implementation range.

## Test Strategy

- Protocol layer: `python3 scripts/test_context_handoff_protocol.py` verifies the actual skill/command ordering and approval contract.
- Documentation layer: `python3 scripts/test_context_handoff_documentation.py` verifies the native-vs-hook-vs-prompt classification and deferred-evidence wording.
- Regression layer: `python3 plugins/ed3d-orchestrate/hooks/test-check-review-loop.py`, `python3 plugins/ed3d-orchestrate/hooks/test-adversary-write-guard.py`, and `python3 scripts/test-dispatch-protocol.py` prove existing hook and dispatch contracts remain intact.
- Repository validation layer: run `python3 scripts/validate_plugins.py` and `python3 scripts/test-dispatch-protocol.py`; no new hook registration is expected.
- Scope layer: `python3 scripts/test_context_handoff_scope.py` accepts a supplied base revision and rejects changed paths outside the bounded allowlist, including hooks, facet/transclusion resources, and unrelated plugins.
- Acceptance mapping: AC.1–AC.2 map to `test_context_handoff_protocol.py`; AC.3 maps to `test_context_handoff_documentation.py`; AC.4 maps to the existing hook/dispatch suites plus protocol source-presence assertions; AC.5 maps to `test_context_handoff_scope.py` and adversarial review.

## Review Strategy

Before implementation, the plan is reviewed by the native `plan-reviewer` workflow for file grounding, acceptance-criterion coverage, test adequacy, and replace-vs-edit risk. After implementation, run the existing `ed3d-orchestrate` adversarial-review/tumble-dryer workflow against the committed range. The adversary must verify the actual protocol/test/docs diff, specifically checking that the approval boundary is explicit, the ordering contract is test-backed, and no hook, facet, or duplicate review behavior was introduced. Any critical/high finding is fixed and re-reviewed; medium/low findings are reported explicitly.

## Documentation Strategy

Update only the existing `plugins/ed3d-orchestrate/skills/orchestrating-the-loop/SKILL.md`, `plugins/ed3d-orchestrate/commands/orchestrate.md`, and `plugins/ed3d-orchestrate/README.md` to make the approval checkpoint and its limits explicit. Use the terms **native Copilot runtime enforcement** (unavailable for this boundary), **repository hook/script enforcement** (deferred until a native builder-dispatch payload and identity are evidenced), and **prompt-only guidance** (the mechanism implemented here). The documentation test checks these distinctions and the unresolved-evidence prerequisite. No `AGENTS.md` or `ROADMAP.md` update is planned because this slice does not land the deferred mechanical gate; if implementation changes the deferred-status wording, the plan must be amended before editing those files. No plugin version bump is planned, so marketplace/changelog synchronization is out of scope; any version change would require a revised plan and the repository's synchronization rules.

## Risks

- **No native approval primitive:** Copilot cannot enforce facet transitions itself. Mitigation: make the operator checkpoint explicit in prompt/protocol text, test its ordering contract, and document that this slice is not runtime enforcement.
- **Prompt compliance is not mechanical enforcement:** An orchestrator could still violate the protocol, and users can bypass the plugin entirely. Mitigation: keep the existing state/review guards unchanged and defer a repository hook backstop until the native builder-dispatch payload and identity are captured and reviewed.
- **Native delegation evidence remains unresolved:** The official hook reference documents `task` as a tool but does not specify an agent/resource identity in the pre-tool payload, and this checkout has no captured builder-dispatch fixture. Mitigation: add no matcher or new hook in this slice; record this as the prerequisite for a future mechanical plan.
- **Duplicate behavior:** Changes could accidentally recreate plan-review or adversarial gates. Mitigation: limit edits to the existing handoff prose, command/README wording, and contract tests; retain existing hook files unchanged and run their regression suites.
- **Audit discrepancy:** The audit's “missing boundary” wording is stale; this plan treats the existing prose boundary as present and implements only a tested prompt/protocol strengthening. Do not rewrite historical evidence artifacts as part of this slice. The plan does not change ROADMAP.md; preserve the audit as historical evidence and leave the mechanical-gate follow-up deferred.
