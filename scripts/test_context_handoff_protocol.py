#!/usr/bin/env python3
"""Deterministic offline tests for the ed3d-orchestrate Context Handoff Gate.

Verifies the protocol slice of the approved 0.5.0 release: the plan-review
pass is followed by an explicit operator approval checkpoint, the mandatory
end-of-turn rule and the no-builder-in-that-turn invariant are preserved, the
explicit-continue approval paths precede the first builder-dispatch
instruction, approval is persisted as ``gate.approval`` in the
pending/granted values, a bare auto-resume is refused (resuming alone does not
grant approval), and no speculative ``gate_pending`` hook contract or new hook
registration is introduced.

Reads only the actual skill, command, and README files on disk. Zero
dependencies.
"""
from __future__ import annotations

import json
import re
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
    # Both paths require an explicit `continue`; `/clear` alone is only a
    # context handoff and does not approve or transfer ownership.
    assert "reply **continue** to approve and start the builders in this context" in body
    assert (
        "first record `transfer_pending`, run `/clear`, then "
        "`/ed3d-orchestrate:orchestrate resume` and reply **continue** in the fresh context"
        in body
    )
    assert "`/clear` alone is only a context handoff, not approval or ownership transfer" in body


def test_approval_wording_precedes_first_builder_dispatch_in_skill():
    body = text(SKILL)
    approval_idx = body.index("## Context Handoff Gate")
    # The first builder-dispatch instruction in the skill is Phase 4's fan-out.
    fanout_idx = body.index("Fan out builders")
    assert approval_idx < fanout_idx, "approval checkpoint must precede builder dispatch"
    # Both explicit-continue approval paths must lie after the gate heading and
    # before the first builder-dispatch instruction as well.
    continue_idx = body.index(
        "reply **continue** to approve and start the builders in this context"
    )
    clear_resume_idx = body.index(
        "first record `transfer_pending`, run `/clear`, then "
        "`/ed3d-orchestrate:orchestrate resume` and reply **continue** in the fresh context"
    )
    assert approval_idx < continue_idx < fanout_idx, (
        "the same-context continue approval phrase must lie after the gate heading "
        "and before the first builder dispatch"
    )
    assert approval_idx < clear_resume_idx < fanout_idx, (
        "the `/clear` + resume continue approval phrase must lie after the gate heading "
        "and before the first builder dispatch"
    )


def test_command_uses_consistent_approval_terminology():
    body = text(COMMAND)
    assert "operator approval checkpoint" in body
    assert "approval paths" in body
    assert "continue" in body and "/clear" in body and "resume" in body
    assert "before any builder dispatch" in body


def test_gate_approval_persisted_pending_granted():
    body = text(SKILL)
    # The state schema documents the gate block with approval pending/granted.
    assert '"gate": {' in body
    assert '"approval": "pending"' in body
    assert '"granted"' in body
    # Approval is read from the file, never implied.
    assert "`gate.approval` is read from the state file, never implied" in body
    # A bare resume does not grant approval; dispatch requires a granted value.
    assert "bare auto-resume is refused" in body
    command_body = text(COMMAND)
    assert 'gate.approval: "pending"' in command_body
    assert 'gate.approval: "granted"' in command_body


def test_existing_state_fields_remain_and_no_gate_pending_contract():
    body = text(SKILL)
    # The documented state fields remain the documented fields, now including
    # the persisted gate block.
    for field in ('"plan_path"', '"base_sha"', '"head_sha"', '"phase"', '"review"', '"gate":'):
        assert field in body, f"missing documented state field {field}"
    # The gate must reference the existing gate.approval field, not a
    # speculative gate_pending hook flag.
    assert 'phase: "execute"' in body
    assert "gate.approval" in body
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


def test_fresh_task_reset_and_validated_resume_are_explicit():
    skill = text(SKILL)
    command = text(COMMAND)
    for body in (skill, command):
        assert "non-empty task argument always starts a fresh loop" in body
        assert "empty invocation may resume only" in body
        assert 'phase: "execute" or "review"' in body
        assert "non-empty absolute `plan_path` that exists" in body
        assert "task matches the plan context" in body
        assert "clean fresh combination" in body
        assert "malformed, partial, legacy, or mismatched state fails closed" in body
    assert '"handoff": {' in skill
    assert '"status": "not_started"' in skill
    assert '"correction_attempts": 0' in skill
    assert '"remaining_outcomes": []' in skill
    assert "reset every task, plan, approval, SHA, and review field" in skill


def test_pending_reset_handoff_is_recorded_and_not_authorization():
    skill = text(SKILL)
    command = text(COMMAND)
    for body in (skill, command):
        assert "reset_pending: true" in body
        assert "requested_task:" in body
        assert "prior_task:" in body
        assert "prior_plan_path:" in body
        assert "approval: pending" in body
        assert "pending record, not authorization" in body
        assert "reset_pending: false" in body
    assert "missing, duplicated, or does not match" in skill
    assert "execution remains refused" in skill


def test_outcome_handoff_is_verified_before_review_and_recovery_is_bounded():
    body = text(SKILL)
    assert "Outcome Handoff" in body
    assert "one concise row for every approved `AC.n`" in body
    assert "complete, incomplete, or blocked" in body
    assert "changed location" in body
    assert "behavior-specific command/result" in body
    assert "before recording `head_sha` or arming adversarial review" in body
    assert "one missing-outcome correction" in body
    assert "correction_attempts" in body
    assert "dispatch the existing `task-bug-fixer` once" in body
    assert "second incomplete handoff" in body
    assert 'handoff.status: "blocked"' in body
    assert "review.active: false" in body
    assert "requires an explicit takeover/replan decision" in body


def test_successful_handoff_correction_persists_verified_state():
    body = text(SKILL)
    correction_idx = body.index("On the first missing/incomplete requested outcome")
    success_idx = body.index("If the fixer completes", correction_idx)
    review_idx = body.index(
        "before recording `head_sha` or arming review", success_idx
    )
    assert correction_idx < success_idx < review_idx
    success = body[success_idx:review_idx]
    assert 'handoff.status: "verified"' in success
    assert 'correction_attempts: 1' in success
    assert "remaining_outcomes: []" in success
    assert "Re-read" in success
    assert "Do not arm adversarial review while the handoff is pending" in body


def test_command_checks_handoff_after_builder_completion():
    body = text(COMMAND)
    dispatch_idx = body.index("builder dispatch")
    completion_idx = body.index("After all builders have reported")
    review_idx = body.index("review armed")
    assert dispatch_idx < completion_idx < review_idx
    assert "Before any builder dispatch, the orchestrator checks" not in body
    skill = text(SKILL)
    assert skill.index("Fan out builders") < skill.index(
        "After all builders have reported"
    )
    assert skill.index("After all builders have reported") < skill.index(
        "Only after this handoff check succeeds"
    )


def _canonical_state(body: str) -> dict:
    marker = "At loop start, create `.ed3d/orchestrate-state.json`"
    start = body.index(marker)
    match = re.search(r"```json\n(.*?)\n```", body[start:], re.DOTALL)
    assert match, "canonical fresh-state JSON example is missing"
    return json.loads(match.group(1))


def _assert_canonical_defaults(state: dict) -> None:
    assert state["task"] == "one-line description of the task"
    assert state["plan_path"] is None
    assert state["base_sha"] is None
    assert state["head_sha"] is None
    assert state["phase"] == "research"
    assert state["gate"] == {"approval": "pending"}
    assert state["handoff"] == {
        "status": "not_started",
        "correction_attempts": 0,
        "remaining_outcomes": [],
    }
    assert state["ownership"] == {
        "status": "unowned",
        "session_id": None,
        "transfer_from": None,
    }
    assert state["review"] == {
        "active": False,
        "round": 0,
        "max_rounds": 3,
        "verdict": "PENDING",
        "open_critical_high": [],
        "consecutive_blocks": 0,
        "history": [],
        "nonce": None,
        "provenance": None,
        "recovery": {
            "status": "none",
            "attempts": 0,
            "marker": None,
        },
    }


def test_canonical_reset_defaults_and_stale_review_mutations_are_detected():
    state = _canonical_state(text(SKILL))
    _assert_canonical_defaults(state)
    for key, value in (
        ("max_rounds", 99),
        ("nonce", "stale123"),
        ("consecutive_blocks", 6),
    ):
        mutated = json.loads(json.dumps(state))
        mutated["review"][key] = value
        try:
            _assert_canonical_defaults(mutated)
        except AssertionError:
            pass
        else:
            raise AssertionError(f"stale review mutation was not detected: {key}")


def test_state_transition_and_verdict_re_read_checklists_are_explicit():
    skill = text(SKILL)
    adversarial = text(ROOT / "plugins/ed3d-orchestrate/skills/adversarial-review/SKILL.md")
    for body in (skill, adversarial):
        assert "transition checklist" in body
        assert "fresh task" in body
        assert "plan binding" in body
        assert "approval" in body
        assert "review arm" in body
        assert "verdict" in body
        assert "FIX-FIRST" in body
        assert "terminal SHIP" in body
    assert "persist and re-read" in adversarial
    assert "highest round value" in adversarial
    assert "same-round `PENDING` entry" in adversarial
    assert "atomic temporary-file replacement" in adversarial
    assert "does not protect concurrent model-mediated state edits" in adversarial


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
