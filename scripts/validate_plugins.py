#!/usr/bin/env python3
"""Structural validator for ed3d-plugins Copilot compatibility work.

Checks (strict - failures exit 1):
  1. The 14 Copilot-native agent twins exist, with:
     - strict-quoted frontmatter (parseable; every scalar quoted or a
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
     (including commands/orchestrate.md), and the review-policy/protocol
     strings (verdict markers, verdict write-back atomicity, review.history
     schema, adversary no-writes rule, git baseline preflight, auto-resume)
     exist in the adversary agent, both loop skills, and the orchestrate
     command
  4. .claude-plugin/marketplace.json parses, contains an ed3d-orchestrate
     entry whose source resolves, and every plugin source resolves

Warnings (do not affect exit status): pre-existing markdown frontmatter
outside the strict set that fails parse or quoting lint.

Zero external dependencies (stdlib only): the frontmatter parser is built
in and handles exactly the scalar grammar the strict set uses.
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SANCTIONED_LINE = "Do not dispatch or invoke subagents; return directly to your caller."

# 14 expected twins: path -> expected model (None = model key must be absent).
# Copilot-native twins inherit the account's Auto/default model selection.
EXPECTED_TWINS = {
    "plugins/ed3d-plan-and-execute/agents/task-implementor-fast.agent.md": None,
    "plugins/ed3d-plan-and-execute/agents/code-reviewer.agent.md": None,
    "plugins/ed3d-plan-and-execute/agents/task-bug-fixer.agent.md": None,
    "plugins/ed3d-plan-and-execute/agents/test-analyst.agent.md": None,
    "plugins/ed3d-research-agents/agents/internet-researcher.agent.md": None,
    "plugins/ed3d-research-agents/agents/codebase-investigator.agent.md": None,
    "plugins/ed3d-research-agents/agents/remote-code-researcher.agent.md": None,
    "plugins/ed3d-research-agents/agents/combined-researcher.agent.md": None,
    "plugins/ed3d-basic-agents/agents/haiku-general-purpose.agent.md": None,
    "plugins/ed3d-basic-agents/agents/sonnet-general-purpose.agent.md": None,
    "plugins/ed3d-basic-agents/agents/opus-general-purpose.agent.md": None,
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

POLICY_FORBIDDEN = {
    # Copilot dispatch prompts must inherit model and effort selection from account Auto/default.
    "plugins/ed3d-orchestrate/agents/adversary.agent.md": [
        "model:", "reasoning_effort:", "effort:", "effortLevel:",
        "kimi-k3", "gpt-5.6-luna", "gemini-3.5-flash", "Always pin", "pinned model",
    ],
    "plugins/ed3d-orchestrate/agents/plan-reviewer.agent.md": [
        "model:", "reasoning_effort:", "effort:", "effortLevel:",
        "kimi-k3", "gpt-5.6-luna", "gemini-3.5-flash", "Always pin", "pinned model",
    ],
    "plugins/ed3d-orchestrate/commands/orchestrate.md": [
        "model:", "reasoning_effort:", "effort:", "effortLevel:",
        "kimi-k3", "gpt-5.6-luna", "gemini-3.5-flash", "Always pin", "pinned model",
    ],
    "plugins/ed3d-orchestrate/skills/adversarial-review/SKILL.md": [
        "model:", "reasoning_effort:", "effort:", "effortLevel:",
        "kimi-k3", "gpt-5.6-luna", "gemini-3.5-flash", "Always pin", "pinned model",
    ],
    "plugins/ed3d-orchestrate/skills/orchestrating-the-loop/SKILL.md": [
        "model:", "reasoning_effort:", "effort:", "effortLevel:",
        "kimi-k3", "gpt-5.6-luna", "gemini-3.5-flash", "Always pin", "pinned model",
    ],
    "plugins/ed3d-orchestrate/skills/scout-sweep/SKILL.md": [
        "model:", "reasoning_effort:", "effort:", "effortLevel:",
        "kimi-k3", "gpt-5.6-luna", "gemini-3.5-flash", "Always pin", "pinned model",
    ],
}

AGENT_DISPATCH_POLICY = (
    "Invoke the named resource through Copilot's native agent/subagent delegation mechanism; "
    "do not call the Skill loader for agent names."
)

POLICY_TARGETS = {
    "plugins/ed3d-orchestrate/agents/adversary.agent.md": [
        "critical", "high", "medium", "low",
        "VERDICT: SHIP", "VERDICT: FIX-FIRST", "has_critical_or_high",
        # no-writes rule (0.3.0): the adversary never maintains loop state
        "you never write `.ed3d/orchestrate-state.json`, never modify the working tree, never commit",
        # 0.3.3: nonce-tagged output contract + hardened no-writes posture
        "VERDICT: SHIP [nonce]",
        "report, do not repair",
    ],
    "plugins/ed3d-orchestrate/skills/adversarial-review/SKILL.md": [
        AGENT_DISPATCH_POLICY,
        "critical", "high", "medium", "low",
        "VERDICT: SHIP", "VERDICT: FIX-FIRST", "max_rounds",
        # verdict write-back atomicity (0.3.0): commit in the same turn as parsing
        "A verdict that is not in the state file does not exist",
        "The guardrail reads the file, not your intentions",
        # review.history round record (0.3.0)
        '"history": [',
        '{"round": 1, "verdict": "FIX-FIRST", "critical_high": 1, "advisory": 6}',
        '{"round": 2, "verdict": "SHIP", "critical_high": 0, "advisory": 0}',
        '{"round": N, "verdict": "PENDING", "critical_high": 0, "advisory": 0, "note": "adversary protocol failure"}',
        # resume reconciliation (0.3.0)
        "Resume reconciliation",
        # verdict commit checklist with re-read verification (0.3.1)
        "Use this checklist and do not skip the re-read",
        "consecutive_blocks: 0",
        # git baseline precondition (0.3.1)
        "both are valid commits in the current git repository",
        # terminal-state verification (0.3.1)
        "verify the terminal state",
        # 0.3.3: nonce generated on arming (incl. re-arm for a new loop),
        # head_sha refresh after fixer commits, PENDING re-arm before re-dispatch
        "Whenever a review arms — including re-arming an existing inactive review block",
        "refresh `head_sha` in the state file to the new full 40-character",
        'and `verdict` to `"PENDING"` in the same state-file write',
        # Auto/default model inheritance: model and effort selection are intentionally omitted.
        "Use the account's Auto/default model selection",
        "Do not select a model or set an effort override",
    ],
    "plugins/ed3d-orchestrate/skills/orchestrating-the-loop/SKILL.md": [
        AGENT_DISPATCH_POLICY,
        # verdict write-back atomicity (0.3.0)
        "A verdict that is not in the state file does not exist",
        "The guardrail reads the file, not your intentions",
        "Commit the verdict to the state file in the same turn first",
        # review.history round record (0.3.0)
        '"history": [',
        '{"round": 1, "verdict": "FIX-FIRST", "critical_high": 1, "advisory": 6}',
        '{"round": 2, "verdict": "SHIP", "critical_high": 0, "advisory": 0}',
        # git baseline preflight + SHA recording (0.3.1)
        "verify the git baseline",
        '"base_sha": null',
        '"head_sha": null',
        "record `head_sha` from the current `HEAD`",
        # terminal-state verification before final report (0.3.1)
        "review.consecutive_blocks: 0",
        # auto-resume rationalization (0.3.1)
        "Not if a state file exists. Resume the recorded loop first.",
        # 0.3.3: loop nonce schema + lifecycle, PENDING-means-in-flight invariant,
        # write-guard as the mechanical enforcement layer
        '"nonce": null',
        "generate a fresh nonce",
        "adversary dispatch is in flight",
        "write-guard hook mechanically blocks write-class tool calls",
        # Auto/default model inheritance: model selection is intentionally omitted.
        "leaving model selection to the account's Auto/default",
        "Do not select or pin a model in dispatch instructions",
    ],
    "plugins/ed3d-orchestrate/skills/scout-sweep/SKILL.md": [
        AGENT_DISPATCH_POLICY,
        "Use the account's Auto/default model selection",
        "Send no model or effort override",
    ],
    "plugins/ed3d-orchestrate/commands/orchestrate.md": [
        # auto-resume mode (0.3.1) + bounded state-file discovery (0.3.2)
        "records an in-progress loop (`review.active` is true, or `review.verdict` is not `SHIP`)",
        "do not restart or repeat completed phases",
        "resolve the root with `git rev-parse --show-toplevel`",
        "never request access to directories outside the project",
        # git baseline requirement (0.3.1)
        "requires a local git repository with at least one commit",
        "record a valid `BASE_SHA` before builder execution",
        # 0.3.3: resume cd-to-root after locating the state file
        "`cd` to the repository root you resolved it from",
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


def decode_scalar(raw):
    """Decode a frontmatter scalar per the grammar QUOTED_VALUE enforces."""
    if raw == "true":
        return True
    if raw == "false":
        return False
    if raw == "null":
        return None
    if raw.startswith('"') and raw.endswith('"'):
        try:
            return json.loads(raw)
        except ValueError:
            return raw[1:-1]
    if raw.startswith("'") and raw.endswith("'"):
        return raw[1:-1].replace("''", "'")
    try:
        return int(raw)
    except ValueError:
        return float(raw)


def lint_frontmatter(fm_text, path, strict):
    """Lint + parse flat scalar frontmatter (stdlib only, no PyYAML).

    The grammar is exactly the frontmatter shape the strict set uses: one
    ``key: value`` scalar (or bare ``key:``) per line. Lines outside that
    grammar are reported as problems; keys whose own line is well-formed
    still parse. Returns the parsed dict, or None when nothing parsed.
    """
    problems = []
    parsed = {}
    for line in fm_text.split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = QUOTED_VALUE.match(line)
        if match:
            key = line.split(":", 1)[0].strip()
            parsed[key] = decode_scalar(match.group(1))
            continue
        if KEY_ONLY.match(line):
            key = line.split(":", 1)[0].strip()
            parsed[key] = None
            continue
        problems.append("unquoted or non-scalar frontmatter value: %r" % line)
    if not parsed:
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
    for path, needles in POLICY_FORBIDDEN.items():
        if not os.path.isfile(os.path.join(ROOT, path)):
            fail("missing forbidden-policy target: %s" % path)
            continue
        text = read(path)
        for needle in needles:
            if needle in text:
                fail("%s: forbidden policy string present %r" % (path, needle))


def check_agent_markup_repo_wide():
    for dirpath, _dirnames, filenames in os.walk(os.path.join(ROOT, "plugins")):
        for filename in filenames:
            if filename.endswith(".agent.md"):
                rel = os.path.relpath(os.path.join(dirpath, filename), ROOT)
                text = read(rel)
                if "<example>" in text or "<commentary>" in text:
                    fail("%s: contains <example>/<commentary> markup" % rel)


def check_skill_names_repo_wide():
    """Every skills/<dir>/SKILL.md frontmatter name equals <dir> (0.3.3).

    Tolerant extraction by regex: the strict frontmatter grammar covers
    the orchestrate set only, and most of the repo uses unquoted names,
    which lint_frontmatter parses as None.
    """
    name_line = re.compile(r'^name:\s*"?([A-Za-z0-9_-]+)"?\s*$', re.MULTILINE)
    for dirpath, dirnames, _filenames in os.walk(os.path.join(ROOT, "plugins")):
        if os.path.basename(dirpath) != "skills":
            continue
        for dirname in sorted(dirnames):
            skill_md = os.path.join(dirpath, dirname, "SKILL.md")
            if not os.path.isfile(skill_md):
                continue
            rel = os.path.relpath(skill_md, ROOT)
            fm_text, _ = split_frontmatter(read(rel), rel)
            if fm_text is None:
                fail("%s: no frontmatter" % rel)
                continue
            match = name_line.search(fm_text)
            name = match.group(1) if match else None
            if name != dirname:
                fail("%s: skill frontmatter name %r != directory %r" % (rel, name, dirname))


def check_write_guard_registration():
    """hooks.json must keep the adversary write-guard armed (0.3.3).

    Registered under preToolUse with a matcher covering the observed
    Copilot write tools (edit/create/apply_patch) or a catch-all; the
    hook's in-process WRITE_TOOLS set is the authority either way.
    Matcher drift silently disarms the guard, so it is pinned here.
    """
    path = "plugins/ed3d-orchestrate/hooks/hooks.json"
    try:
        data = json.loads(read(path))
    except (OSError, json.JSONDecodeError) as exc:
        fail("hooks.json: %s" % exc)
        return
    registered = False
    matcher_ok = False
    for entry in data.get("hooks", {}).get("preToolUse", []):
        for hook in entry.get("hooks", []):
            if "adversary-write-guard.py" not in str(hook.get("command", "")):
                continue
            registered = True
            matcher = str(entry.get("matcher", ""))
            if matcher == "":
                matcher_ok = True  # catch-all: the hook's WRITE_TOOLS is the authority
            else:
                try:
                    pattern = re.compile(matcher)
                    matcher_ok = all(pattern.search(tool) for tool in ("edit", "create", "apply_patch"))
                except re.error:
                    matcher_ok = False
    if not registered:
        fail("hooks.json: adversary-write-guard.py not registered under preToolUse")
    elif not matcher_ok:
        fail("hooks.json: write-guard preToolUse matcher does not cover the observed write tools (edit/create/apply_patch) or a catch-all")


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
    check_skill_names_repo_wide()
    check_write_guard_registration()
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
