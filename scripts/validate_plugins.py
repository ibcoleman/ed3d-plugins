#!/usr/bin/env python3
"""Structural validator for ed3d-plugins Copilot compatibility work.

Checks (strict - failures exit 1):
  1. The 14 Copilot-native agent twins exist, with:
     - strict-quoted frontmatter (parseable YAML; every scalar quoted or a
       bare true/false/null/number)
     - name matching the filename stem
     - a non-empty description with no <example>/<commentary> markup
     - the model binding matching the expected role map (or absent for
       inherit-default agents)
     - no Claude-only frontmatter keys (color, disallowedTools)
     - body byte-verbatim vs the source .md, plus exactly one sanctioned
       no-nested-subagent line
  2. No <example>/<commentary> markup in any .agent.md in the repo
  3. plugins/ed3d-orchestrate/ agent/skill/command frontmatter is strict
     (including commands/orchestrate.md), and the review-policy strings and
     verdict markers exist in the adversary agent + adversarial-review skill
  4. .claude-plugin/marketplace.json parses, contains an ed3d-orchestrate
     entry whose source resolves, and every plugin source resolves

Warnings (do not affect exit status): pre-existing markdown frontmatter
outside the strict set that fails parse or quoting lint.

PyYAML is required for this script only:
    pip install pyyaml
"""
import json
import os
import re
import sys

try:
    import yaml
except ImportError:
    print("error: PyYAML is required for scripts/validate_plugins.py")
    print("       install it with: pip install pyyaml")
    sys.exit(1)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SANCTIONED_LINE = "Do not dispatch or invoke subagents; return directly to your caller."

# 14 expected twins: path -> expected model (None = key must be absent)
EXPECTED_TWINS = {
    "plugins/ed3d-plan-and-execute/agents/task-implementor-fast.agent.md": "gpt-5.6-luna",
    "plugins/ed3d-plan-and-execute/agents/code-reviewer.agent.md": "kimi-k3",
    "plugins/ed3d-plan-and-execute/agents/task-bug-fixer.agent.md": "gpt-5.6-luna",
    "plugins/ed3d-plan-and-execute/agents/test-analyst.agent.md": "kimi-k3",
    "plugins/ed3d-research-agents/agents/internet-researcher.agent.md": "gpt-5.6-luna",
    "plugins/ed3d-research-agents/agents/codebase-investigator.agent.md": "gpt-5.6-luna",
    "plugins/ed3d-research-agents/agents/remote-code-researcher.agent.md": "gpt-5.6-luna",
    "plugins/ed3d-research-agents/agents/combined-researcher.agent.md": "gpt-5.6-luna",
    "plugins/ed3d-basic-agents/agents/haiku-general-purpose.agent.md": "gpt-5.6-luna",
    "plugins/ed3d-basic-agents/agents/sonnet-general-purpose.agent.md": "gpt-5.6-luna",
    "plugins/ed3d-basic-agents/agents/opus-general-purpose.agent.md": "kimi-k3",
    "plugins/ed3d-session-reflection/agents/conversation-reviewer.agent.md": None,
    "plugins/ed3d-playwright/agents/playwright-explorer.agent.md": None,
    "plugins/ed3d-extending-claude/agents/project-claude-librarian.agent.md": None,
}

ALLOWED_TWIN_KEYS = {"name", "description", "model", "tools"}
CLAUDE_ONLY_KEYS = {"color", "disallowedTools"}

ORCHESTRATE_STRICT_MD = [
    "plugins/ed3d-orchestrate/agents/adversary.agent.md",
    "plugins/ed3d-orchestrate/agents/plan-reviewer.agent.md",
    "plugins/ed3d-orchestrate/skills/orchestrating-the-loop/SKILL.md",
    "plugins/ed3d-orchestrate/skills/adversarial-review/SKILL.md",
    "plugins/ed3d-orchestrate/skills/scout-sweep/SKILL.md",
    "plugins/ed3d-orchestrate/commands/orchestrate.md",
]

POLICY_TARGETS = {
    "plugins/ed3d-orchestrate/agents/adversary.agent.md": [
        "critical", "high", "medium", "low",
        "VERDICT: SHIP", "VERDICT: FIX-FIRST", "has_critical_or_high",
    ],
    "plugins/ed3d-orchestrate/skills/adversarial-review/SKILL.md": [
        "critical", "high", "medium", "low",
        "VERDICT: SHIP", "VERDICT: FIX-FIRST", "max_rounds",
    ],
}

QUOTED_VALUE = re.compile(
    r'^[A-Za-z][\w-]*:\s+'
    r'("(?:[^"\\]|\\.)*"'      # double-quoted
    r"|'(?:[^']|'')*'"         # single-quoted
    r"|true|false|null"        # bare booleans/null
    r"|-?\d+(?:\.\d+)?)"       # bare numbers
    r"\s*$"
)
KEY_ONLY = re.compile(r"^[A-Za-z][\w-]*:\s*$")

failures = []
warnings = []


def fail(msg):
    failures.append(msg)


def warn(msg):
    warnings.append(msg)


def read(path):
    with open(os.path.join(ROOT, path), encoding="utf-8") as handle:
        return handle.read()


def split_frontmatter(text, path):
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return None, None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            return "\n".join(lines[1:index]), "\n".join(lines[index + 1:])
    return None, None


def lint_frontmatter(fm_text, path, strict):
    """Parse + quoting lint. Returns parsed dict or None."""
    problems = []
    for line in fm_text.split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not (QUOTED_VALUE.match(line) or KEY_ONLY.match(line)):
            problems.append("unquoted or non-scalar frontmatter value: %r" % line)
    try:
        parsed = yaml.safe_load(fm_text)
    except yaml.YAMLError as exc:
        problems.append("YAML parse error: %s" % str(exc).split("\n")[0])
        parsed = None
    if parsed is not None and not isinstance(parsed, dict):
        problems.append("frontmatter is not a mapping")
        parsed = None
    for problem in problems:
        (fail if strict else warn)("%s: %s" % (path, problem))
    return parsed


def check_twin(path, expected_model):
    full = os.path.join(ROOT, path)
    if not os.path.isfile(full):
        fail("missing twin: %s" % path)
        return
    text = read(path)
    if "<example>" in text or "<commentary>" in text:
        fail("%s: contains <example>/<commentary> markup" % path)
    fm_text, body = split_frontmatter(text, path)
    if fm_text is None:
        fail("%s: no frontmatter" % path)
        return
    parsed = lint_frontmatter(fm_text, path, strict=True)
    if parsed is None:
        return
    stem = os.path.basename(path)[: -len(".agent.md")]
    if parsed.get("name") != stem:
        fail("%s: frontmatter name %r != filename stem %r" % (path, parsed.get("name"), stem))
    description = parsed.get("description")
    if not isinstance(description, str) or not description.strip():
        fail("%s: missing or empty description" % path)
    for key in CLAUDE_ONLY_KEYS:
        if key in parsed:
            fail("%s: Claude-only frontmatter key %r present" % (path, key))
    extra = set(parsed.keys()) - ALLOWED_TWIN_KEYS
    if extra:
        fail("%s: unexpected frontmatter keys: %s" % (path, sorted(extra)))
    if expected_model is None:
        if "model" in parsed:
            fail("%s: model key present but role map says inherit (omit)" % path)
    else:
        if parsed.get("model") != expected_model:
            fail("%s: model %r != expected %r" % (path, parsed.get("model"), expected_model))

    # body must be the source body verbatim + the sanctioned line
    source_path = path[: -len(".agent.md")] + ".md"
    if not os.path.isfile(os.path.join(ROOT, source_path)):
        fail("%s: source agent missing: %s" % (path, source_path))
        return
    _, source_body = split_frontmatter(read(source_path), source_path)
    if source_body is None:
        fail("%s: source has no frontmatter/body split" % source_path)
        return
    expected_body = source_body.rstrip("\n") + "\n\n" + SANCTIONED_LINE + "\n"
    if body.rstrip("\n") + "\n" != expected_body:
        fail("%s: body is not source-verbatim + sanctioned line" % path)
    if body.count(SANCTIONED_LINE) != 1:
        fail("%s: sanctioned line appears %d times (expected 1)" % (path, body.count(SANCTIONED_LINE)))


def check_orchestrate_file(path):
    if not os.path.isfile(os.path.join(ROOT, path)):
        fail("missing ed3d-orchestrate file: %s" % path)
        return
    text = read(path)
    fm_text, _ = split_frontmatter(text, path)
    if fm_text is None:
        fail("%s: no frontmatter" % path)
        return
    parsed = lint_frontmatter(fm_text, path, strict=True)
    if parsed is None:
        return
    if not isinstance(parsed.get("description"), str) or not parsed.get("description", "").strip():
        fail("%s: missing or empty description" % path)
    if path.endswith(".agent.md"):
        stem = os.path.basename(path)[: -len(".agent.md")]
        if parsed.get("name") != stem:
            fail("%s: frontmatter name %r != stem %r" % (path, parsed.get("name"), stem))
    if path.endswith("SKILL.md"):
        skill_dir = os.path.basename(os.path.dirname(os.path.join(ROOT, path)))
        if parsed.get("name") != skill_dir:
            fail("%s: skill name %r != directory %r" % (path, parsed.get("name"), skill_dir))


def check_command():
    path = "plugins/ed3d-orchestrate/commands/orchestrate.md"
    if not os.path.isfile(os.path.join(ROOT, path)):
        fail("missing command file: %s" % path)
        return
    text = read(path)
    fm_text, _ = split_frontmatter(text, path)
    if fm_text is None:
        fail("%s: no frontmatter" % path)
        return
    parsed = lint_frontmatter(fm_text, path, strict=True)
    if parsed is None:
        return
    if "argument-hint" not in parsed:
        fail("%s: missing argument-hint" % path)


def check_policy_strings():
    for path, needles in POLICY_TARGETS.items():
        if not os.path.isfile(os.path.join(ROOT, path)):
            fail("missing policy target: %s" % path)
            continue
        text = read(path)
        for needle in needles:
            if needle not in text:
                fail("%s: missing policy string %r" % (path, needle))


def check_agent_markup_repo_wide():
    for dirpath, _dirnames, filenames in os.walk(os.path.join(ROOT, "plugins")):
        for filename in filenames:
            if filename.endswith(".agent.md"):
                rel = os.path.relpath(os.path.join(dirpath, filename), ROOT)
                text = read(rel)
                if "<example>" in text or "<commentary>" in text:
                    fail("%s: contains <example>/<commentary> markup" % rel)


def check_marketplace():
    path = os.path.join(ROOT, ".claude-plugin", "marketplace.json")
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        fail("marketplace.json: %s" % exc)
        return
    entries = data.get("plugins", [])
    names = [entry.get("name") for entry in entries]
    if "ed3d-orchestrate" not in names:
        fail("marketplace.json: no ed3d-orchestrate entry")
    for entry in entries:
        source = entry.get("source")
        if not isinstance(source, str):
            fail("marketplace.json: entry %r has no source" % entry.get("name"))
            continue
        # Relative sources in marketplace.json resolve from the repo root
        # (the parent of .claude-plugin/), not from the marketplace file itself.
        target = os.path.normpath(os.path.join(ROOT, source))
        if not os.path.isdir(target):
            fail("marketplace.json: source of %r does not resolve: %s" % (entry.get("name"), source))
    orchestrate = next((e for e in entries if e.get("name") == "ed3d-orchestrate"), None)
    if orchestrate is not None:
        target = os.path.normpath(os.path.join(ROOT, orchestrate["source"]))
        if not os.path.isdir(os.path.join(target, ".claude-plugin")):
            fail("marketplace.json: ed3d-orchestrate source has no .claude-plugin/plugin.json dir")
        plugin_json = os.path.join(target, ".claude-plugin", "plugin.json")
        if os.path.isfile(plugin_json):
            try:
                with open(plugin_json, encoding="utf-8") as handle:
                    manifest = json.load(handle)
                if manifest.get("version") != orchestrate.get("version"):
                    fail("marketplace/plugin.json version mismatch for ed3d-orchestrate: %r vs %r"
                         % (orchestrate.get("version"), manifest.get("version")))
            except (OSError, json.JSONDecodeError) as exc:
                fail("ed3d-orchestrate plugin.json: %s" % exc)
        else:
            fail("ed3d-orchestrate: missing .claude-plugin/plugin.json")


def scan_preexisting_warnings():
    strict = set(EXPECTED_TWINS) | set(ORCHESTRATE_STRICT_MD)
    for dirpath, _dirnames, filenames in os.walk(os.path.join(ROOT, "plugins")):
        for filename in filenames:
            if not filename.endswith(".md"):
                continue
            rel = os.path.relpath(os.path.join(dirpath, filename), ROOT)
            if rel in strict:
                continue
            fm_text, _ = split_frontmatter(read(rel), rel)
            if fm_text is None:
                continue  # not frontmatter markdown; not our concern
            lint_frontmatter(fm_text, rel, strict=False)


def main():
    for twin_path, model in EXPECTED_TWINS.items():
        check_twin(twin_path, model)
    for path in ORCHESTRATE_STRICT_MD:
        check_orchestrate_file(path)
    check_command()
    check_policy_strings()
    check_agent_markup_repo_wide()
    check_marketplace()
    scan_preexisting_warnings()

    print("strict checks: %d failure(s)" % len(failures))
    for item in failures:
        print("  FAIL %s" % item)
    print("warnings (pre-existing style, not gating): %d" % len(warnings))
    for item in warnings:
        print("  warn %s" % item)
    if failures:
        return 1
    print("OK: all strict checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
