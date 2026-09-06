#!/usr/bin/env python3
"""Deterministic offline test for the ed3d-orchestrate plan-artifact contract.

The orchestrate workflow writes exactly one planning artifact: the plan
document at ``docs/implementation-plans/<YYYY-MM-DD>-<slug>/plan.md``. Phase 2
is read-only — the plan document itself is the only thing written in that
phase — and the state file records its absolute path as ``plan_path`` so the
loop can resume from it.

This test asserts that "plan.md-only" contract against both the skill's prose
and the checked-in plan artifacts:

  - the skill documents the plan path as ``docs/implementation-plans/
    <YYYY-MM-DD>-<slug>/plan.md`` and names ``plan.md`` as the artifact,
  - Phase 2 planning is documented as read-only (the plan is the only write),
  - ``plan_path`` is recorded in the state file pointing at the plan document,
  - every plan directory under docs/implementation-plans/ contains exactly one
    top-level artifact named ``plan.md``.

Zero dependencies. Exit 0 when the contract holds; exit 1 otherwise.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "plugins/ed3d-orchestrate/skills/orchestrating-the-loop/SKILL.md"
PLANS = ROOT / "docs/implementation-plans"

PLAN_PATH_TEMPLATE = "docs/implementation-plans/<YYYY-MM-DD>-<slug>/plan.md"


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_skill_documents_plan_path_template():
    body = text(SKILL)
    assert PLAN_PATH_TEMPLATE in body, "skill must document the plan.md path template"


def test_plan_artifact_is_named_plan_md():
    body = text(SKILL)
    # The plan artifact is always named plan.md (the contract is plan.md-only).
    assert "/plan.md" in body


def test_planning_is_read_only():
    body = text(SKILL)
    assert "read-only" in body
    assert "The plan document itself is the only thing you write in this phase" in body


def test_plan_path_recorded_in_state():
    body = text(SKILL)
    assert "plan_path" in body
    assert "set `plan_path` in the state file to its absolute path" in body


def test_checked_in_plans_are_plan_md_only():
    # Each plan directory must contain exactly one top-level plan artifact, the
    # plan.md file — no other plan-named top-level file.
    dirs = [d for d in PLANS.iterdir() if d.is_dir()]
    assert dirs, "expected at least one checked-in plan directory"
    for d in sorted(dirs):
        plan = d / "plan.md"
        assert plan.exists(), f"{d.name}: missing plan.md artifact"
        # The plan directory's top-level files must be exactly {plan.md}.
        top = {p.name for p in d.iterdir() if p.is_file()}
        assert top == {"plan.md"}, (
            f"{d.name}: plan directory must contain only plan.md, got {sorted(top)}"
        )


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
    print(f"{len(TESTS) - len(failures)}/{len(TESTS)} plan-artifact contract tests passed")
    raise SystemExit(1 if failures else 0)
