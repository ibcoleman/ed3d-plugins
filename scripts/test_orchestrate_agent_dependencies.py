#!/usr/bin/env python3
"""Deterministic offline test for the ed3d-orchestrate builder/fixer agent twins.

ed3d-orchestrate dispatches builders and fixers from ed3d-plan-and-execute.
Each such agent ships as a pair of "twins": a Claude Code ``*.md`` original and
a Copilot-native ``*.agent.md`` copy. Per the README, the Copilot twins preserve
the role bodies from their Claude Code originals while intentionally omitting
Claude-only frontmatter keys (``model``, ``color``, ``disallowedTools``).

This test asserts the exact-twin contract for the builder and fixer:

  - each named builder/fixer has both ``*.md`` and ``*.agent.md`` present,
  - the body after the YAML frontmatter is byte-identical between the twins,
    except the ``.agent.md`` appends the "Do not dispatch or invoke subagents;
    return directly to your caller." return line,
  - the ``.agent.md`` omits the Claude-only frontmatter keys,
  - the ``.agent.md`` carries the dispatch-return guard line.

Zero dependencies. Exit 0 when the twins hold; exit 1 otherwise.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENTS = ROOT / "plugins/ed3d-plan-and-execute/agents"

# The builder/fixer twins ed3d-orchestrate depends on.
BUILDERS = ("task-implementor-fast",)
FIXERS = ("task-bug-fixer",)

# Claude-only frontmatter keys that the Copilot-native twins must omit.
CLAUDE_ONLY_KEYS = ("model", "color", "disallowedTools")

RETURN_GUARD = "Do not dispatch or invoke subagents; return directly to your caller."


def split_frontmatter(body: str) -> tuple[str, str]:
    """Return (frontmatter, content) for a file with a leading YAML block."""
    assert body.startswith("---"), "expected a leading YAML frontmatter block"
    parts = body.split("---", 2)
    assert len(parts) == 3, "expected a closed YAML frontmatter block"
    return parts[1], parts[2]


def normalize_agent_body(content: str) -> str:
    """Strip the trailing dispatch-return guard line from an .agent.md body so
    the remaining body can be compared against the Claude original."""
    text = content.rstrip("\n")
    if RETURN_GUARD in text:
        text = text.rsplit(RETURN_GUARD, 1)[0]
    return text.rstrip("\n") + "\n"


def agent_pairs():
    for name in (*BUILDERS, *FIXERS):
        yield name, AGENTS / f"{name}.md", AGENTS / f"{name}.agent.md"


def test_twins_exist():
    for name, md, agent in agent_pairs():
        assert md.exists(), f"missing Claude twin: {md}"
        assert agent.exists(), f"missing Copilot twin: {agent}"


def test_bodies_are_exact_twins():
    for name, md, agent in agent_pairs():
        _, md_content = split_frontmatter(md.read_text(encoding="utf-8"))
        _, agent_content = split_frontmatter(agent.read_text(encoding="utf-8"))
        assert md_content == normalize_agent_body(agent_content), (
            f"{name}: .agent.md body is not an exact twin of the .md body "
            "(apart from the dispatch-return line)"
        )


def test_agent_md_omits_claude_only_frontmatter():
    for name, md, agent in agent_pairs():
        frontmatter, _ = split_frontmatter(agent.read_text(encoding="utf-8"))
        for key in CLAUDE_ONLY_KEYS:
            assert key not in frontmatter, (
                f"{name}.agent.md must omit the Claude-only key {key!r}"
            )
        # The Claude original keeps its pinned frontmatter keys.
        md_frontmatter, _ = split_frontmatter(md.read_text(encoding="utf-8"))
        for key in CLAUDE_ONLY_KEYS:
            assert key in md_frontmatter, (
                f"{name}.md should retain the Claude frontmatter key {key!r}"
            )


def test_agent_md_carries_dispatch_return_guard():
    for name, md, agent in agent_pairs():
        body = agent.read_text(encoding="utf-8")
        assert RETURN_GUARD in body, (
            f"{name}.agent.md must carry the dispatch-return guard line"
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
    print(f"{len(TESTS) - len(failures)}/{len(TESTS)} orchestrate agent-dependency (twin) tests passed")
    raise SystemExit(1 if failures else 0)
