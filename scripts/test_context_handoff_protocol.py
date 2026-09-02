#!/usr/bin/env python3
"""Deterministic offline tests for the ed3d-orchestrate Context Handoff Gate.

Verifies the prompt/protocol slice of the selective-polytoken-handoff-gate plan:
that the plan-review pass is followed by an explicit operator approval
checkpoint, the mandatory end-of-turn rule and the no-builder-in-that-turn
invariant are preserved, the two approval paths (`continue` and `/clear` +
resume) precede the first builder-dispatch instruction, and no speculative
`gate_pending` hook contract or new state field is introduced.

Reads only the actual skill and command files on disk. Zero dependencies.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "plugins/ed3d-orchestrate/skills/orchestrating-the-loop/SKILL.md"
COMMAND = ROOT / "plugins/ed3d-orchestrate/commands/orchestrate.md"
README = ROOT / "plugins/ed3d-orchestrate/README.md"


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_gate_contains_approval_language():
    body = text(SKILL)
    assert "## Context Handoff Gate" in body
    assert "operator approval checkpoint" in body
    assert "not merely a context-management suggestion" in body
    assert "approval paths" in body
    assert "continue" in body and "/clear" in body and "resume" in body
    assert "plan-review pass" in body
    assert "before any builder dispatch" in body


def test_mandatory_stop_and_end_of_turn_preserved():
    body = text(SKILL)
    assert "**Mandatory:**" in body
    assert "**End your turn**" in body
    assert "stops at this approval checkpoint" in body


def test_no_builder_in_that_turn_invariant():
    body = text(SKILL)
    assert "ANY builder" in body
    assert "before dispatching" in body
    assert "Do not dispatch builders in the same turn in which the gate passed" in body
    assert "only after the operator's approval response" in body
    assert "start the builders in this context" in body


def test_two_approval_paths_are_documented():
    body = text(SKILL)
    # Both `continue` and `/clear` + resume must be present as approval paths.
    assert "reply **continue** to approve" in body
    assert "`/clear` and then `/ed3d-orchestrate:orchestrate resume` to approve" in body


def test_approval_wording_precedes_first_builder_dispatch_in_skill():
    body = text(SKILL)
    approval_idx = body.index("## Context Handoff Gate")
    # The first builder-dispatch instruction in the skill is Phase 4's fan-out.
    fanout_idx = body.index("Fan out builders")
    assert approval_idx < fanout_idx, "approval checkpoint must precede builder dispatch"
    # The `continue` approval path must appear before the first dispatch too.
    assert body.index("reply **continue**") < fanout_idx
    # The `/clear` + resume approval path must lie after the gate heading and
    # before the first builder-dispatch instruction as well.
    clear_resume_idx = body.index(
        "`/clear` and then `/ed3d-orchestrate:orchestrate resume` to approve"
    )
    assert approval_idx < clear_resume_idx < fanout_idx, (
        "the `/clear` + resume approval phrase must lie after the gate heading "
        "and before the first builder dispatch"
    )


def test_command_uses_consistent_approval_terminology():
    body = text(COMMAND)
    assert "operator approval checkpoint" in body
    assert "approval paths" in body
    assert "continue" in body and "/clear" in body and "resume" in body
    assert "before any builder dispatch" in body


def test_existing_state_fields_remain_and_no_gate_pending_contract():
    body = text(SKILL)
    # The documented state fields remain the documented fields.
    for field in ('"plan_path"', '"base_sha"', '"head_sha"', '"phase"', '"review"'):
        assert field in body, f"missing documented state field {field}"
    # The gate must reference the existing fields, not a speculative gate flag.
    assert 'phase: "execute"' in body
    assert "gate_pending" not in body, "speculative gate_pending hook contract introduced"
    command_body = text(COMMAND)
    assert "gate_pending" not in command_body
    readme_body = text(README)
    assert "gate_pending" not in readme_body


def test_no_new_hook_or_duplicate_gate_claims_in_skill():
    body = text(SKILL)
    # Only one plan-review gate is documented; the handoff gate is an approval
    # checkpoint, not a second plan-review/adversarial review gate.
    assert body.count("## Context Handoff Gate") == 1
    assert "gate_pending" not in body
    # The existing hook files are not referenced as new registrations.
    assert "hooks.json" not in body


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
    print(f"{len(TESTS) - len(failures)}/{len(TESTS)} context-handoff protocol tests passed")
    raise SystemExit(1 if failures else 0)
