#!/usr/bin/env python3
"""Deterministic offline tests for the Context Handoff Gate documentation.

Verifies the approved 0.5.0 release's documentation contracts for the
plan-review -> builder handoff boundary:

  - the persisted ``gate.approval`` pending/granted semantics are documented
    (the field is written to the state file, never implied),
  - the boundary is classified as protocol-only guidance (Branch B): it is
    prompt-only guidance, not native Copilot runtime enforcement and not
    repository hook/script enforcement, with the mechanical backstop deferred
    until a native builder-dispatch payload and identity are evidenced,
  - approval is explicit and processed later (after the operator's response),
    before any builder dispatch,
  - a bare auto-resume is refused (resuming alone does not grant approval),
  - no builder is dispatched in the same turn the gate passed,
  - no speculative ``gate_pending`` hook contract is introduced (the persisted
    field is ``gate.approval``), and the existing hooks remain unchanged.

Zero dependencies.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "plugins/ed3d-orchestrate/skills/orchestrating-the-loop/SKILL.md"
README = ROOT / "plugins/ed3d-orchestrate/README.md"
COMMAND = ROOT / "plugins/ed3d-orchestrate/commands/orchestrate.md"


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_skill_distinguishes_native_vs_prompt_vs_hook():
    body = text(SKILL)
    assert "prompt-only guidance" in body
    assert "native Copilot runtime enforcement" in body
    assert "repository hook/script enforcement" in body
    assert "unavailable" in body
    assert "deferred" in body


def test_readme_distinguishes_native_vs_prompt_vs_hook():
    body = text(README)
    assert "prompt-only guidance" in body
    assert "native Copilot runtime enforcement" in body
    assert "repository hook/script enforcement" in body
    assert "unavailable" in body
    assert "deferred" in body


def test_missing_builder_dispatch_evidence_named_as_prerequisite():
    # Both docs must name the missing native builder-dispatch payload and
    # identity as the prerequisite for a future mechanical slice.
    skill = text(SKILL)
    readme = text(README)
    for body in (skill, readme):
        assert "builder-dispatch" in body
        assert "payload" in body and "identity" in body
        assert "evidenced" in body
    # The deferral must be tied to that evidence, not to a version or deploy issue.
    assert "deferred until a native builder-dispatch payload and identity are evidenced" in skill
    assert "deferred until a native builder-dispatch payload and identity are evidenced" in readme


def test_docs_assert_persisted_gate_approval_semantics():
    skill = text(SKILL)
    command_body = text(COMMAND)
    # The skill documents gate.approval as persisted operator-approval state
    # with pending/granted values, and ties dispatch to a granted value in the file.
    assert "gate.approval" in skill
    assert "persisted operator-approval state" in skill
    assert '"pending"' in skill and '"granted"' in skill
    assert 'no builder dispatch may occur while `gate.approval` is not `"granted"` in the file' in skill
    # The command gates builder dispatch on the persisted pending/granted values.
    assert 'gate.approval: "pending"' in command_body
    assert 'gate.approval: "granted"' in command_body


def test_docs_assert_protocol_only_branch_b():
    skill = text(SKILL)
    readme = text(README)
    # README names the protocol-only Branch B decision and its evidence artifact.
    assert "protocol-only" in readme
    assert "Branch B" in readme
    assert "docs/research/2026-09-03-orchestrate-enforcement-branch-b.evidence.md" in readme
    # Both docs frame the boundary as prompt-only guidance, not mechanical and
    # not native runtime enforcement.
    assert "prompt-only guidance" in skill and "prompt-only guidance" in readme
    assert "not **native Copilot runtime enforcement**" in skill
    assert "no native Copilot runtime enforcement" in readme
    assert "not mechanical" in readme
    assert "unavailable" in skill and "unavailable" in readme
    assert "deferred" in skill and "deferred" in readme


def test_docs_assert_later_explicit_approval():
    skill = text(SKILL)
    readme = text(README)
    command_body = text(COMMAND)
    # Approval is explicit, processed later (after the operator's response),
    # and always precedes any builder dispatch.
    assert "only after the operator's approval response" in skill
    assert "in a **later** turn" in skill
    assert "approval write always precedes the dispatch" in skill
    assert "processed before any builder dispatch" in readme
    assert "only after the operator's explicit" in command_body


def test_docs_assert_bare_auto_resume_refused():
    skill = text(SKILL)
    command_body = text(COMMAND)
    # Resuming alone does not grant approval; a bare auto-resume is refused.
    assert "bare auto-resume is refused" in skill
    assert "resuming alone does not grant approval" in skill
    assert "bare auto-resume is refused" in command_body


def test_docs_assert_no_same_turn_dispatch():
    skill = text(SKILL)
    assert "Do not dispatch builders in the same turn" in skill
    # The persisted gate.approval field gates that dispatch.
    assert "gate.approval" in skill


def test_no_speculative_gate_pending_contract():
    # The persisted field is gate.approval; no doc may introduce a speculative
    # gate_pending hook contract.
    for body in (text(SKILL), text(README), text(COMMAND)):
        assert "gate_pending" not in body


def test_existing_hooks_declared_unchanged():
    readme = text(README)
    assert "check-review-loop.py" in readme
    assert "adversary-write-guard.py" in readme
    assert "unchanged" in readme


TESTS = [name for name in globals() if name.startswith("test_")]


if __name__ == "__main__":
    failures = []
    for name in sorted(TESTS):
        try:
            globals()[name]()
            print(f"PASS {name}")
        except Exception as exc:  # deterministic, concise standalone output
            failures.append((name, exc))
            print(f"FAIL {name}: {exc}")
    print(f"{len(TESTS) - len(failures)}/{len(TESTS)} context-handoff documentation tests passed")
    raise SystemExit(1 if failures else 0)
