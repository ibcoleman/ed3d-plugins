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

OVERRIDE_KEYS = ("model:", "reasoning_effort:", "effort:", "effortLevel:")
FORBIDDEN_GLOBAL_STRINGS = ("gemini-3.5-flash", "Always pin", "pinned model")

# These are raw-text bans. Preferred literals are allowed only inside the bounded
# dispatch sections below; agent frontmatter and command prose remain model-free.
POLICY_FORBIDDEN = {
    path: list(OVERRIDE_KEYS) + list(FORBIDDEN_GLOBAL_STRINGS)
    for path in ORCHESTRATE_STRICT_MD
}

AGENT_DISPATCH_POLICY = (
    "Invoke the named resource through Copilot's native agent/subagent delegation mechanism; "
    "do not call the Skill loader for agent names."
)
DISPATCH_BEGIN = "<!-- DISPATCH-PROTOCOL:BEGIN -->"
DISPATCH_END = "<!-- DISPATCH-PROTOCOL:END -->"
SKILL_PATHS = [
    "plugins/ed3d-orchestrate/skills/adversarial-review/SKILL.md",
    "plugins/ed3d-orchestrate/skills/orchestrating-the-loop/SKILL.md",
    "plugins/ed3d-orchestrate/skills/scout-sweep/SKILL.md",
]
OLD_NO_MODEL_NEEDLES = (
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

POLICY_TARGETS = {
    "plugins/ed3d-orchestrate/agents/adversary.agent.md": [
        "critical", "high", "medium", "low", "VERDICT: SHIP", "VERDICT: FIX-FIRST", "has_critical_or_high",
        "you never write `.ed3d/orchestrate-state.json`, never modify the working tree, never commit",
        "VERDICT: SHIP [nonce]", "report, do not repair",
    ],
    "plugins/ed3d-orchestrate/skills/adversarial-review/SKILL.md": [
        AGENT_DISPATCH_POLICY, "critical", "high", "medium", "low", "VERDICT: SHIP", "VERDICT: FIX-FIRST", "max_rounds",
        "A verdict that is not in the state file does not exist", "The guardrail reads the file, not your intentions", '"history": [',
        '{"round": 1, "verdict": "FIX-FIRST", "critical_high": 1, "advisory": 6}', '{"round": 2, "verdict": "SHIP", "critical_high": 0, "advisory": 0}',
        '{"round": N, "verdict": "PENDING", "critical_high": 0, "advisory": 0, "note": "adversary protocol failure"}', "Resume reconciliation",
        "Use this checklist and do not skip the re-read", "consecutive_blocks: 0", "both are valid commits in the current git repository",
        "verify the terminal state", "Whenever a review arms — including re-arming an existing inactive review block",
        "refresh `head_sha` in the state file to the new full 40-character", 'and `verdict` to `"PENDING"` in the same state-file write',
        DISPATCH_BEGIN, DISPATCH_END, "adversary` dispatch", "task-bug-fixer", "kimi-k3", "gpt-5.6-luna", "reasoning_effort=", "pre-start rejection",
        "rate-limit", "protocol-failure", "ambiguous", "full response",
    ],
    "plugins/ed3d-orchestrate/skills/orchestrating-the-loop/SKILL.md": [
        AGENT_DISPATCH_POLICY, "A verdict that is not in the state file does not exist", "The guardrail reads the file, not your intentions",
        "Commit the verdict to the state file in the same turn first", '"history": [',
        '{"round": 1, "verdict": "FIX-FIRST", "critical_high": 1, "advisory": 6}', '{"round": 2, "verdict": "SHIP", "critical_high": 0, "advisory": 0}',
        "verify the git baseline", '"base_sha": null', '"head_sha": null', "record `head_sha` from the current `HEAD`",
        "review.consecutive_blocks: 0", "Not if a state file exists. Resume the recorded loop first.", '"nonce": null', "generate a fresh nonce",
        "adversary dispatch is in flight", "write-guard hook mechanically blocks write-class tool calls", DISPATCH_BEGIN, DISPATCH_END,
        "plan-reviewer", "task-implementor-fast", "kimi-k3", "gpt-5.6-luna", "reasoning_effort=", "pre-start rejection",
        "rate-limit", "protocol-failure", "ambiguous", "full response",
    ],
    "plugins/ed3d-orchestrate/skills/scout-sweep/SKILL.md": [
        AGENT_DISPATCH_POLICY, DISPATCH_BEGIN, DISPATCH_END, "scouts use pinned-first", "gpt-5.6-luna", "reasoning_effort=", "pre-start rejection",
        "rate-limit", "protocol-failure", "ambiguous", "full response",
    ],
    "plugins/ed3d-orchestrate/commands/orchestrate.md": [
        "records an in-progress loop (`review.active` is true, or `review.verdict` is not `SHIP`)", "do not restart or repeat completed phases",
        "resolve the root with `git rev-parse --show-toplevel`", "never request access to directories outside the project",
        "requires a local git repository with at least one commit", "record a valid `BASE_SHA` before builder execution", "`cd` to the repository root you resolved it from",
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


def dispatch_section(text, path):
    """Return the sole bounded dispatch section, rejecting malformed markers."""
    begins = [m.start() for m in re.finditer(re.escape(DISPATCH_BEGIN), text)]
    ends = [m.start() for m in re.finditer(re.escape(DISPATCH_END), text)]
    if len(begins) != 1 or len(ends) != 1:
        fail("%s: expected exactly one non-nested dispatch marker pair" % path)
        return ""
    if begins[0] >= ends[0]:
        fail("%s: dispatch markers reversed" % path)
        return ""
    body = text[begins[0] + len(DISPATCH_BEGIN):ends[0]]
    if DISPATCH_BEGIN in body or DISPATCH_END in body:
        fail("%s: nested dispatch markers" % path)
        return ""
    return body


def check_dispatch_protocol():
    combined = "\n".join(read(path) for path in SKILL_PATHS)
    for needle in OLD_NO_MODEL_NEEDLES:
        if needle in combined:
            fail("skills: residual old no-model dispatch phrase %r" % needle)
    sections = {path: dispatch_section(read(path), path) for path in SKILL_PATHS}
    for path in ORCHESTRATE_STRICT_MD:
        body = read(path)
        if path in sections:
            bounded = sections[path]
            outside = body.replace(DISPATCH_BEGIN + bounded + DISPATCH_END, "")
            for literal in ("kimi-k3", "gpt-5.6-luna"):
                if literal in outside:
                    fail("%s: preferred literal outside bounded dispatch section %r" % (path, literal))
        else:
            for literal in ("kimi-k3", "gpt-5.6-luna"):
                if literal in body:
                    fail("%s: preferred literal outside dispatch skill %r" % (path, literal))
    required = {
        SKILL_PATHS[0]: ("kimi-k3", "high", "adversary` dispatch", "task-bug-fixer", "gpt-5.6-luna", "medium"),
        SKILL_PATHS[1]: ("kimi-k3", "high", "plan-reviewer", "gpt-5.6-luna", "medium", "task-implementor-fast"),
        SKILL_PATHS[2]: ("gpt-5.6-luna", "low", "scouts use pinned-first"),
    }
    for path, needles in required.items():
        body = sections[path]
        for needle in needles:
            if needle not in body:
                fail("%s: missing bounded dispatch needle %r" % (path, needle))
        if re.search(r"\b(?:high|medium|low)\b", body) is None:
            fail("%s: bounded section has no effort literal" % path)
        for forbidden in ("critical/high", "medium/low"):
            # Severity labels are allowed and must not be mistaken for effort syntax.
            if forbidden in body and re.search(r"reasoning_effort=\"(?:high|medium|low)\"", body) is None:
                fail("%s: bounded section contains severity label %r but no explicit reasoning_effort override; severity labels do not satisfy the effort requirement" % (path, forbidden))
    # Exact site-level positives, scoped to the relevant skill rather than a
    # protocol paragraph in an unrelated file.
    site_needles = {
        SKILL_PATHS[0]: ("Site requirement: the primary `adversary` dispatch is pinned-first", "For the FIX-FIRST branch, dispatch `task-bug-fixer`"),
        SKILL_PATHS[1]: ("Dispatch `plan-reviewer`", "Site requirement: the Phase 4 `task-implementor-fast` dispatch is pinned-first"),
        SKILL_PATHS[2]: ("Site requirement: scouts use pinned-first",),
    }
    for path, needles in site_needles.items():
        body = sections[path]
        for needle in needles:
            if needle not in body:
                fail("%s: missing explicit dispatch-site needle %r" % (path, needle))

    # A role/site must carry its exact model+reasoning_effort pair on the
    # dispatch line itself.  Checking these together prevents severity labels
    # such as ``critical/high`` from satisfying an effort-only substring test.
    site_override_pairs = {
        SKILL_PATHS[0]: (
            ("adversary` dispatch", 'model="kimi-k3"', 'reasoning_effort="high"'),
            ("task-bug-fixer", 'model="gpt-5.6-luna"', 'reasoning_effort="medium"'),
        ),
        SKILL_PATHS[1]: (
            ("plan-reviewer", 'model="kimi-k3"', 'reasoning_effort="high"'),
            ("task-implementor-fast", 'model="gpt-5.6-luna"', 'reasoning_effort="medium"'),
        ),
        SKILL_PATHS[2]: (
            ("each scout's first attempt", 'model="gpt-5.6-luna"', 'reasoning_effort="low"'),
        ),
    }
    for path, pairs in site_override_pairs.items():
        body = sections[path]
        for role, model, effort in pairs:
            if not any(role in line and model in line and effort in line for line in body.splitlines()):
                fail("%s: missing exact model+reasoning_effort pair for %r" % (path, role))


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
    check_dispatch_protocol()


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
