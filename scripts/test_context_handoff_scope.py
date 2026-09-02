#!/usr/bin/env python3
"""Zero-dependency scope test for the selective-polytoken-handoff-gate slice.

Usage: python3 scripts/test_context_handoff_scope.py <base-revision>

Validates that the supplied base revision exists, then inspects the changed-path
set from that revision to the current checkout (tracked changes plus untracked
files) and enforces the exact bounded allowlist for this prompt/protocol slice:

  - plugins/ed3d-orchestrate/skills/orchestrating-the-loop/SKILL.md
  - plugins/ed3d-orchestrate/commands/orchestrate.md
  - plugins/ed3d-orchestrate/README.md
  - scripts/test_context_handoff_protocol.py
  - scripts/test_context_handoff_documentation.py
  - scripts/test_context_handoff_scope.py

Any changed path outside this allowlist is a violation. In particular, changes
to hooks.json, either existing hook script (check-review-loop.py,
adversary-write-guard.py), facet/transclusion resources, unrelated plugins, and
all other unexpected paths are rejected. The plan was not amended to approve
roadmap/changelog/version files, so those are rejected too.

Exit 0 when every changed path is within the allowlist and the base exists;
exit 1 otherwise, listing violations. Zero external dependencies.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Exact bounded allowlist for this slice. The plan was NOT amended to approve
# roadmap/changelog/version files, so no additional paths are permitted.
ALLOWED = frozenset({
    "plugins/ed3d-orchestrate/skills/orchestrating-the-loop/SKILL.md",
    "plugins/ed3d-orchestrate/commands/orchestrate.md",
    "plugins/ed3d-orchestrate/README.md",
    "scripts/test_context_handoff_protocol.py",
    "scripts/test_context_handoff_documentation.py",
    "scripts/test_context_handoff_scope.py",
})

# Explicitly-protected path families that must never appear in the diff.
PROTECTED = (
    "hooks.json",
    "check-review-loop.py",
    "adversary-write-guard.py",
    "facets/",
    "transclusion",
    ".j2",
)


def git(args):
    return subprocess.run(
        ["git", *args],
        cwd=str(ROOT), text=True, capture_output=True, check=False,
    )


def changed_paths(base: str) -> set[str]:
    """Tracked changes from `base` to the working tree, plus untracked files."""
    paths: set[str] = set()
    # Tracked modifications/staged changes between base and the working tree.
    diff = git(["diff", "--name-only", "--no-renames", base])
    if diff.returncode != 0:
        sys.exit(f"error: git diff against {base} failed: {diff.stderr.strip()}")
    paths.update(p for p in diff.stdout.splitlines() if p)
    # New (untracked) files that are not yet part of any commit.
    untracked = git(["ls-files", "--others", "--exclude-standard"])
    if untracked.returncode != 0:
        sys.exit(f"error: git ls-files failed: {untracked.stderr.strip()}")
    paths.update(p for p in untracked.stdout.splitlines() if p)
    return {p for p in paths if p}  # drop empty strings


def main(argv) -> int:
    if len(argv) != 2:
        print("usage: python3 scripts/test_context_handoff_scope.py <base-revision>")
        return 2

    base = argv[1]
    verify = git(["rev-parse", "--verify", "--quiet", f"{base}^{{commit}}"])
    if verify.returncode != 0:
        print(f"FAIL base revision does not resolve to a commit: {base}")
        return 1

    paths = changed_paths(base)
    violations = sorted(p for p in paths if p not in ALLOWED)
    protected_hits = sorted(p for p in violations if any(pat in p for pat in PROTECTED))

    for p in sorted(paths):
        if p in ALLOWED:
            print(f"OK   {p}")
        else:
            print(f"FAIL {p}")

    if violations:
        print(f"FAIL {len(violations)} changed path(s) outside the bounded allowlist")
        if protected_hits:
            print(f"FAIL protected path(s) touched: {protected_hits}")
        return 1

    print("PASS all changed paths are within the bounded Context Handoff Gate allowlist")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
