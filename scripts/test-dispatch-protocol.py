#!/usr/bin/env python3
"""Deterministic static tests for ed3d-orchestrate dispatch protocol prose."""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS = {
    "adversarial": ROOT / "plugins/ed3d-orchestrate/skills/adversarial-review/SKILL.md",
    "loop": ROOT / "plugins/ed3d-orchestrate/skills/orchestrating-the-loop/SKILL.md",
    "scouts": ROOT / "plugins/ed3d-orchestrate/skills/scout-sweep/SKILL.md",
}
BEGIN = "<!-- DISPATCH-PROTOCOL:BEGIN -->"
END = "<!-- DISPATCH-PROTOCOL:END -->"
OLD_PHRASES = (
    "Use the account's Auto/default model selection",
    "Do not select a model or set an effort override",
    "leaving model selection to the account's Auto/default",
    "Do not select or pin a model in dispatch instructions",
    "Send no model or effort override",
    "without model or effort parameters",
    "without model or effort overrides",
    "leave model selection unset",
    "account/CLI defaults decide both",
    "Auto/default applies",
)
STRICT_TARGETS = [
    ROOT / "plugins/ed3d-orchestrate/agents/adversary.agent.md",
    ROOT / "plugins/ed3d-orchestrate/agents/plan-reviewer.agent.md",
    SKILLS["loop"], SKILLS["adversarial"], SKILLS["scouts"],
    ROOT / "plugins/ed3d-orchestrate/commands/orchestrate.md",
]


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def section(path: Path) -> str:
    body = text(path)
    assert body.count(BEGIN) == 1, f"{path}: bounded begin marker count"
    assert body.count(END) == 1, f"{path}: bounded end marker count"
    start = body.index(BEGIN) + len(BEGIN)
    stop = body.index(END)
    assert start < stop, f"{path}: marker order"
    result = body[start:stop]
    assert BEGIN not in result and END not in result, f"{path}: nested marker"
    return result


def all_skills() -> str:
    return "\n".join(text(path) for path in SKILLS.values())


def test_preferred_attempt_is_bounded_and_role_specific():
    adversary = section(SKILLS["adversarial"])
    loop = section(SKILLS["loop"])
    scouts = section(SKILLS["scouts"])
    assert 'adversary` dispatch' in adversary and 'gpt-5.6-sol` / `medium' in adversary
    assert "task-bug-fixer" in adversary and 'gpt-5.6-luna` and effort `high' in adversary
    assert "plan-reviewer" in loop and 'gpt-5.6-luna` and effort `high' in loop
    assert "task-implementor-fast" in loop and 'gpt-5.6-luna` and effort `high' in loop
    assert "scouts use pinned-first `gpt-5.6-luna` / `high`" in scouts
    expected_pairs = (
        ('model="gpt-5.6-sol"', 'reasoning_effort="medium"'),
        ('model="gpt-5.6-luna"', 'reasoning_effort="high"'),
    )
    for body in (adversary, loop, scouts):
        assert any(model in line and effort in line for line in body.splitlines() for model, effort in expected_pairs)
    assert any('adversary` dispatch' in line and 'model="gpt-5.6-sol"' in line and 'reasoning_effort="medium"' in line for line in adversary.splitlines())
    assert any("task-bug-fixer" in line and 'model="gpt-5.6-luna"' in line and 'reasoning_effort="high"' in line for line in adversary.splitlines())
    assert any("plan-reviewer" in line and 'model="gpt-5.6-luna"' in line and 'reasoning_effort="high"' in line for line in loop.splitlines())
    assert any("task-implementor-fast" in line and 'model="gpt-5.6-luna"' in line and 'reasoning_effort="high"' in line for line in loop.splitlines())
    assert any("each scout's first attempt" in line and 'model="gpt-5.6-luna"' in line and 'reasoning_effort="high"' in line for line in scouts.splitlines())
    for path in STRICT_TARGETS:
        if ".agent.md" in path.name:
            assert "model:" not in text(path)


def test_six_no_model_needles_are_replaced():
    combined = all_skills()
    assert "DISPATCH-PROTOCOL:BEGIN" in combined
    assert "DISPATCH-PROTOCOL:END" in combined
    assert "native agent/subagent delegation mechanism" in combined
    assert "do not call the Skill loader for agent names" in combined
    assert "preferred model" in combined
    assert "both the `model` and `reasoning_effort` overrides omitted" in combined
    assert "explicit pre-start" in combined
    assert "adversary` dispatch" in section(SKILLS["adversarial"])
    assert "task-bug-fixer" in section(SKILLS["adversarial"])
    assert "task-implementor-fast" in section(SKILLS["loop"])
    assert "plan-reviewer" in section(SKILLS["loop"])
    assert "scouts use pinned-first" in section(SKILLS["scouts"])
    for phrase in OLD_PHRASES:
        assert phrase not in combined, f"residual old phrase: {phrase}"


def test_no_residual_old_policy_dispatch_phrases():
    combined = all_skills()
    for phrase in OLD_PHRASES:
        assert combined.count(phrase) == 0, phrase
    assert "CLI defaults decide both" not in combined
    assert "Auto/default applies" not in combined


def test_unrelated_protocol_needles_are_verbatim():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/validate_plugins.py")],
        cwd=ROOT, text=True, capture_output=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK: all strict checks passed" in result.stdout


def test_override_keys_are_forbidden_everywhere():
    for path in STRICT_TARGETS:
        body = text(path)
        for key in ("model:", "reasoning_effort:", "effort:", "effortLevel:"):
            assert key not in body, f"{path}: {key}"
        for needle in ("gemini-3.5-flash", "Always pin", "pinned model"):
            assert needle not in body, f"{path}: {needle}"


def test_preferred_literals_are_scoped_to_protocol_sections():
    for path in STRICT_TARGETS:
        body = text(path)
        if path in SKILLS.values():
            bounded = section(path)
            outside = body.replace(BEGIN + bounded + END, "")
            for literal in ("gpt-5.6-sol", "gpt-5.6-luna"):
                assert literal not in outside, f"{path}: unbounded {literal}"
        else:
            assert "gpt-5.6-sol" not in body and "gpt-5.6-luna" not in body
    # Bare severity words and severity labels are not effort overrides.
    assert "critical/high" in text(SKILLS["adversarial"])
    assert "medium/low" in text(SKILLS["adversarial"])


def test_explicit_rejection_has_one_auto_fallback():
    for path in SKILLS.values():
        body = section(path)
        assert "explicit pre-start" in body
        fallback_rules = body.count("exactly one Auto fallback")
        assert fallback_rules >= 1
        assert body.count("both `model` and `reasoning_effort` overrides omitted") == fallback_rules
        assert body.count("fallback rejection is terminal") == fallback_rules


def test_rate_limit_does_not_consume_fallback():
    for path in SKILLS.values():
        body = section(path)
        assert "rate-limit" in body
        assert ("does not consume" in body or "do not consume" in body or "does not consume the model fallback" in body)
        assert "wait" in body and "retry" in body


def test_started_no_verdict_uses_protocol_failure_without_model_fallback():
    for path in SKILLS.values():
        body = section(path)
        assert "started/no-verdict" in body
        assert "protocol-failure" in body
        assert "without model fallback" in body
        assert "ambiguous" in body and "terminal" in body


def test_attempt_ceiling_and_no_duplicate_rule():
    for path in SKILLS.values():
        body = section(path)
        assert "at most three semantic submissions" in body
        assert "one Auto fallback" in body
        fallback_rules = body.count("exactly one Auto fallback")
        assert body.count("never issues the fallback twice") == fallback_rules
        assert body.count("never combines protocol retry with model fallback") == fallback_rules
    combined = all_skills()
    assert combined.count("Never combine protocol retry with model fallback") == 1


def test_preferred_fallback_reporting_and_loader_distinction():
    combined = all_skills()
    assert "preferred success" in combined
    assert "fallback result" in combined
    assert "protocol failure" in combined
    assert "ambiguous" in combined
    assert "native agent/subagent delegation mechanism" in combined
    assert "do not call the Skill loader for agent names" in combined
    for path in SKILLS.values():
        assert "full response" in section(path)


def test_version_readme_roadmap_sync():
    manifest = json.loads(text(ROOT / "plugins/ed3d-orchestrate/.claude-plugin/plugin.json"))
    marketplace = json.loads(text(ROOT / ".claude-plugin/marketplace.json"))
    entry = next(item for item in marketplace["plugins"] if item["name"] == "ed3d-orchestrate")
    assert manifest["version"] == entry["version"] == "0.4.1"
    changelog = text(ROOT / "CHANGELOG.md")
    assert "## [ed3d-orchestrate] [0.4.1]" in changelog
    readme = text(ROOT / "plugins/ed3d-orchestrate/README.md")
    assert "pinned-first" in readme and "best-effort hard-coded" in readme
    assert "transcript/report-only" in readme and "does not survive `/clear` or resume" in readme
    assert "claude-haiku-4.5" in readme and "unknown dispatch-error semantics" in readme
    roadmap = text(ROOT / "ROADMAP.md")
    assert "catalog verification remains dormant" in roadmap
    assert "future catalog/API/operator verification event" in roadmap
    assert "prose pins" in roadmap


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
    print(f"{len(TESTS) - len(failures)}/{len(TESTS)} dispatch protocol tests passed")
    raise SystemExit(1 if failures else 0)
