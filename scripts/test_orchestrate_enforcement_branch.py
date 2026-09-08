#!/usr/bin/env python3
"""Offline Branch B enforcement-branch contract test for ed3d-orchestrate 0.5.0.

Asserts exactly the Branch B contract for the plan-review -> builder handoff
gate: it ships protocol-only. Concretely:

  - The checked-in evidence artifact documents Copilot CLI 1.0.82's validation
    limitation and states the protocol-only status (Branch B).
  - No builder-gate hook artifact exists anywhere in the plugin (no new
    preToolUse script; only check-review-loop.py and adversary-write-guard.py).
  - No builder-gate registration is present in hooks.json (only the two
    existing hooks are registered).
  - No mechanical/runtime enforcement claim is made for the handoff gate in the
    README or the evidence artifact.

Zero dependencies. Exit 0 when Branch B holds; exit 1 otherwise.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/research/2026-09-03-orchestrate-enforcement-branch-b.evidence.md"
HOOKS_JSON = ROOT / "plugins/ed3d-orchestrate/hooks/hooks.json"
ORCH_README = ROOT / "plugins/ed3d-orchestrate/README.md"
HOOKS_DIR = ROOT / "plugins/ed3d-orchestrate/hooks"

# The only hook scripts that may exist / be registered under Branch B.
ALLOWED_HOOKS = frozenset({"check-review-loop.py", "adversary-write-guard.py"})


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_evidence_exists_and_says_protocol_only():
    assert EVIDENCE.exists(), "missing Branch B evidence artifact"
    body = text(EVIDENCE)
    assert "protocol-only" in body
    assert "Branch B" in body
    # protocol-only explicitly means no mechanical enforcement.
    assert "not mechanical" in body or "no mechanical" in body


def test_evidence_documents_validation_limitation():
    body = text(EVIDENCE)
    assert "Copilot CLI 1.0.82" in body
    assert "validation" in body
    assert "limitation" in body


def test_no_builder_gate_artifact():
    # No builder-gate hook artifact may exist anywhere in the plugin (the
    # pre-existing hook scripts and their test suites are fine; only a
    # builder-gate-named artifact would violate Branch B).
    for p in (ROOT / "plugins/ed3d-orchestrate").rglob("*"):
        if p.is_file() and ("builder-gate" in p.name or "builder_gate" in p.name):
            raise AssertionError(f"builder-gate artifact present: {p}")


def test_no_builder_gate_registration():
    assert HOOKS_JSON.exists()
    data = json.loads(text(HOOKS_JSON))
    registered: set[str] = set()
    for events in data["hooks"].values():
        for group in events:
            for hook in group.get("hooks", []):
                cmd = hook.get("command", "")
                assert "builder-gate" not in cmd and "builder_gate" not in cmd, cmd
                for name in ALLOWED_HOOKS:
                    if name in cmd:
                        registered.add(name)
    assert registered == ALLOWED_HOOKS, (
        f"builder-gate registration or missing/extra hooks in hooks.json: {registered}"
    )


def test_no_mechanical_claims():
    # The handoff gate is documented as prompt-only guidance, not mechanical or
    # native runtime enforcement, and the README names no builder-gate artifact.
    readme = text(ORCH_README)
    assert "prompt-only guidance" in readme
    assert "no native Copilot runtime enforcement" in readme
    assert "not mechanical" in readme
    # Evidence states the gate is not mechanical.
    assert "not mechanical" in text(EVIDENCE) or "no mechanical" in text(EVIDENCE)


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
    print(f"{len(TESTS) - len(failures)}/{len(TESTS)} enforcement-branch (Branch B) tests passed")
    raise SystemExit(1 if failures else 0)
