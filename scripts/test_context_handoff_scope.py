#!/usr/bin/env python3
"""Zero-dependency scope test for the approved ed3d-orchestrate 0.5.0 release.

Usage: python3 scripts/test_context_handoff_scope.py <base-revision>

Validates that the supplied base revision exists, then inspects the changed-path
set from that revision to the current checkout (tracked changes plus untracked
files) and enforces the approved 0.5.0 release allowlist:

  - the ed3d-orchestrate implementation docs (SKILL.md, orchestrate.md, README.md),
  - the current-main reconciliation paths for the dispatch policy
    (ORCHESTRATE_BRIEF.md, the adversarial-review and scout-sweep SKILL.md files,
    and scripts/validate_plugins.py),
  - the orchestrate/context-handoff contract test suites under scripts/,
  - the replay fixtures under scripts/fixtures/orchestrate-events/,
  - the Branch B evidence artifact (docs/research/*.evidence.md),
  - the version/manifest/docs/state files for the release (plugin.json,
    marketplace.json, CHANGELOG.md, root README.md, ROADMAP.md,
    getting-started.md, the plan-and-execute README, and plan artifacts under
    docs/implementation-plans/).

Any changed path outside this allowlist is a violation. In particular, changes
to hooks.json, any hook script (check-review-loop.py, adversary-write-guard.py,
anything under hooks/), facet/transclusion resources, and all other unexpected
paths are rejected.

Exit 0 when every changed path is within the allowlist and the base exists;
exit 1 otherwise, listing violations. Zero external dependencies.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Approved 0.5.0 release: exact changed paths that are permitted.
ALLOWED_PATHS = frozenset({
    # Current-main reconciliation paths (ed3d-orchestrate dispatch policy).
    "ORCHESTRATE_BRIEF.md",
    "plugins/ed3d-orchestrate/skills/adversarial-review/SKILL.md",
    "plugins/ed3d-orchestrate/skills/scout-sweep/SKILL.md",
    "scripts/validate_plugins.py",
    # ed3d-orchestrate implementation docs.
    "plugins/ed3d-orchestrate/skills/orchestrating-the-loop/SKILL.md",
    "plugins/ed3d-orchestrate/commands/orchestrate.md",
    "plugins/ed3d-orchestrate/README.md",
    # Orchestrate / context-handoff test suites (existing and new).
    "scripts/test_context_handoff_protocol.py",
    "scripts/test_context_handoff_documentation.py",
    "scripts/test_context_handoff_scope.py",
    "scripts/test_orchestrate_enforcement_branch.py",
    "scripts/test_orchestrate_event_replay.py",
    "scripts/test_orchestrate_agent_dependencies.py",
    "scripts/test_plan_artifact_contract.py",
    "scripts/test-dispatch-protocol.py",
    # Branch B evidence artifact.
    "docs/research/2026-09-03-orchestrate-enforcement-branch-b.evidence.md",
    # Version / manifest / docs / state files for the release.
    ".claude-plugin/marketplace.json",
    "plugins/ed3d-orchestrate/.claude-plugin/plugin.json",
    "CHANGELOG.md",
    "README.md",
    "ROADMAP.md",
    ".gitignore",
    "plugins/ed3d-00-getting-started/commands/getting-started.md",
    "plugins/ed3d-plan-and-execute/README.md",
    "scripts/__pycache__/validate_plugins.cpython-314.pyc",
})

# Directory families permitted for the release (replay fixtures, plan artifacts).
ALLOWED_PREFIXES = (
    "scripts/fixtures/orchestrate-events/",
    "docs/implementation-plans/",
)

# Explicitly-protected path families that must never appear in the diff.
PROTECTED = (
    "hooks.json",
    "hooks/",
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


def allowed(path: str) -> bool:
    """A path is allowed when it is an exact release path or an allowed family,
    and never when it matches a protected path."""
    if path in ALLOWED_PATHS:
        return True
    if any(path.startswith(prefix) for prefix in ALLOWED_PREFIXES):
        return True
    return False


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
    violations = sorted(p for p in paths if not allowed(p))
    protected_hits = sorted(p for p in violations if any(pat in p for pat in PROTECTED))

    for p in sorted(paths):
        if allowed(p):
            print(f"OK   {p}")
        else:
            print(f"FAIL {p}")

    if violations:
        print(f"FAIL {len(violations)} changed path(s) outside the approved 0.5.0 release allowlist")
        if protected_hits:
            print(f"FAIL protected path(s) touched: {protected_hits}")
        return 1

    print("PASS all changed paths are within the approved ed3d-orchestrate 0.5.0 release allowlist")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
