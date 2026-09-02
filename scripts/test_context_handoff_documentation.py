#!/usr/bin/env python3
"""Deterministic offline tests for the Context Handoff Gate documentation.

Verifies that the README and skill correctly classify the handoff boundary as
prompt-only guidance, state that native Copilot runtime enforcement is
unavailable, defer repository hook/script enforcement pending native
builder-dispatch evidence, and do not overstate deployment/version-drift
limitations for this prompt-only slice. Zero dependencies.
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


def test_prompt_only_slice_does_not_claim_runtime_enforcement():
    # No doc may claim native runtime enforcement or a newly registered hook.
    # The full native/prompt/hook classification lives in the skill and README;
    # the command only needs to avoid claiming enforcement.
    skill = text(SKILL)
    readme = text(README)
    assert "gate_pending" not in skill and "gate_pending" not in readme
    # The skill disclaims native runtime enforcement in its exact words.
    assert "not **native Copilot runtime enforcement**" in skill
    assert "enforcement is unavailable" in skill
    # The README disclaims native runtime enforcement in its exact words.
    assert "there is no native Copilot runtime enforcement for it" in readme
    assert "no repository hook/script backstop" in readme
    command_body = text(COMMAND)
    assert "gate_pending" not in command_body
    assert "enforcement" not in command_body
    # The README explicitly marks the checkpoint as not enforced by the harness.
    assert "prompt-only guidance" in readme
    assert "there is no native Copilot runtime enforcement for it" in readme
    assert "no repository hook/script backstop" in readme


def test_deployment_version_drift_limits_not_overstated():
    readme = text(README)
    # This prompt-only slice introduces no deployment or version-drift limitation.
    assert "no deployment or version-drift limitation is implied" in readme
    # It does not claim a version bump or new hook registration.
    assert "hooks.json" not in readme


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
