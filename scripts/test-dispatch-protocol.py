#!/usr/bin/env python3
"""Offline regression tests for configured Copilot dispatch and release metadata."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS = {
    "adversarial": "plugins/ed3d-orchestrate/skills/adversarial-review/SKILL.md",
    "loop": "plugins/ed3d-orchestrate/skills/orchestrating-the-loop/SKILL.md",
    "scouts": "plugins/ed3d-orchestrate/skills/scout-sweep/SKILL.md",
}
BEGIN = "<!-- DISPATCH-PROTOCOL:BEGIN -->"
END = "<!-- DISPATCH-PROTOCOL:END -->"


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def section(path: Path) -> str:
    body = text(path)
    assert body.count(BEGIN) == body.count(END) == 1, f"{path}: marker count"
    start = body.index(BEGIN) + len(BEGIN)
    stop = body.index(END)
    assert start < stop, f"{path}: marker order"
    return " ".join(body[start:stop].split())


def load_validator():
    spec = importlib.util.spec_from_file_location("validate_plugins", ROOT / "scripts/validate_plugins.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fixture_errors(path=None, addition="", remove=""):
    validator = load_validator()
    common = (
        "Omit both `model` and `reasoning_effort` on every dispatch. "
        "Use Copilot's configured subagent settings. "
        "Keep rate-limit handling separate; wait and retry once. "
        "A started/no-verdict result uses the existing protocol-failure path. "
        "An ambiguous outcome is terminal; do not retry. Print the full response."
    )
    roles = {
        SKILLS["adversarial"]: "adversary task-bug-fixer",
        SKILLS["loop"]: "plan-reviewer task-implementor-fast",
        SKILLS["scouts"]: "scouts",
    }
    fixtures = {name: "" for name in validator.ORCHESTRATE_STRICT_MD}
    for name in ("README.md", "plugins/ed3d-orchestrate/README.md", "ORCHESTRATE_BRIEF.md"):
        fixtures[name] = "Use Copilot's configured subagent settings."
    for name, names in roles.items():
        fixtures[name] = f"{BEGIN}\n{common}\n{names}\n{END}\n"
    if path:
        fixtures[path] = fixtures[path].replace(remove, "") if remove else fixtures[path]
        fixtures[path] += addition
    with tempfile.TemporaryDirectory(prefix="dispatch-policy-") as directory:
        root = Path(directory)
        for name, body in fixtures.items():
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body, encoding="utf-8")
        validator.ROOT = directory
        validator.check_dispatch_protocol()
        return validator.failures


def test_validator_accepts_configured_settings_fixture():
    assert fixture_errors() == []


def test_validator_allows_prose_and_severity_labels():
    assert fixture_errors(
        "plugins/ed3d-orchestrate/README.md",
        addition="\nStart a session with a high-reasoning model:\n\n```\n/orchestrate\n```\n"
        "Severity: critical/high findings block; medium/low findings are advisory.",
    ) == []


def test_validator_rejects_reintroduced_pins():
    assert fixture_errors() == [], "positive control must pass before mutation checks"
    mutations = (
        (SKILLS["adversarial"], '\nmodel="gpt-6-astra"'),
        (SKILLS["loop"], '\nreasoning_effort="high"'),
        (SKILLS["scouts"], '\n<parameter name="model">auto</parameter>'),
        ("plugins/ed3d-orchestrate/agents/adversary.agent.md", '\nmodel: "auto"'),
        ("plugins/ed3d-orchestrate/commands/orchestrate.md", '\n{"reasoning_effort": "high"}'),
        ("README.md", "\nDispatch is pinned-first."),
        ("plugins/ed3d-orchestrate/README.md", "\nPrefer gpt-5.6-luna."),
        ("ORCHESTRATE_BRIEF.md", "\nMake one Auto fallback."),
    )
    for path, addition in mutations:
        errors = fixture_errors(path, addition=addition)
        assert any(path in error for error in errors), (path, addition, errors)


def test_validator_rejects_missing_policy_and_broken_markers():
    for missing in (
        "Omit both `model` and `reasoning_effort` on every dispatch.",
        "Copilot's configured subagent settings",
        "task-bug-fixer",
        END,
    ):
        errors = fixture_errors(SKILLS["adversarial"], remove=missing)
        assert any(SKILLS["adversarial"] in error for error in errors), (missing, errors)


def test_every_dispatch_role_inherits_settings():
    for name, roles in (
        ("adversarial", ("adversary", "task-bug-fixer")),
        ("loop", ("plan-reviewer", "task-implementor-fast")),
        ("scouts", ("scouts",)),
    ):
        body = section(ROOT / SKILLS[name])
        assert "Omit both `model` and `reasoning_effort` on every dispatch" in body, name
        assert "Copilot's configured subagent settings" in body, name
        for role in roles:
            assert role in body, (name, role)


def test_failure_handling_and_review_inputs_are_preserved():
    for path in SKILLS.values():
        body = section(ROOT / path)
        assert "rate-limit" in body and "once" in body, path
        assert "started/no-verdict" in body and "protocol-failure" in body, path
        assert "ambiguous" in body and "do not retry" in body.lower(), path
        assert "full response" in body, path
        assert "working directory" in body, path
    adversary = section(ROOT / SKILLS["adversarial"])
    for value in ("BASE_SHA", "HEAD_SHA", "NONCE", "prior issues"):
        assert value in adversary, value
    loop = section(ROOT / SKILLS["loop"])
    assert "PLAN_PATH" in loop and "REPO_ROOT" in loop
    body = text(ROOT / SKILLS["adversarial"])
    assert "critical/high" in body and "medium/low" in body


def test_strict_plugin_validation():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/validate_plugins.py")],
        cwd=ROOT, text=True, capture_output=True, check=False,
    )
    assert result.returncode == 0, result.stdout.split("warnings (", 1)[0] + result.stderr
    assert "OK: all strict checks passed" in result.stdout


def test_both_workflows_and_session_reflection_are_release_synced():
    marketplace = json.loads(text(ROOT / ".claude-plugin/marketplace.json"))
    changelog = text(ROOT / "CHANGELOG.md")
    for name in ("ed3d-orchestrate", "ed3d-native-orchestration", "ed3d-session-reflection"):
        entries = [item for item in marketplace["plugins"] if item["name"] == name]
        assert len(entries) == 1, name
        manifest = json.loads(text(ROOT / "plugins" / name / ".claude-plugin/plugin.json"))
        assert entries[0]["version"] == manifest["version"], name
        assert entries[0]["source"] == f"./plugins/{name}", name
        assert f'## [{name}] [{manifest["version"]}]' in changelog, name
    assert f'Catalog version is {marketplace["version"]}' in changelog


TESTS = [name for name in globals() if name.startswith("test_")]


if __name__ == "__main__":
    sys.dont_write_bytecode = True
    failures = []
    for name in sorted(TESTS):
        try:
            globals()[name]()
            print(f"PASS {name}")
        except Exception as exc:
            failures.append((name, exc))
            print(f"FAIL {name}: {exc}")
    print(f"{len(TESTS) - len(failures)}/{len(TESTS)} dispatch protocol tests passed")
    raise SystemExit(1 if failures else 0)
