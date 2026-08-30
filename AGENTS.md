# ed3d-plugins — Working Instructions for Copilot CLI

As of 2026-08-31 this repository targets GitHub Copilot CLI. New packages and all new development target Copilot CLI. Claude Code is no longer developed against or tested; the existing Claude Code plugins remain published as frozen legacy (bugfix-only at the operator's discretion). GitHub Copilot CLI reads this file as its primary instructions, so keep it authoritative and current.

## Conventions

### Consult ROADMAP.md Before Planning New Work

`ROADMAP.md` at the repo root records deferred follow-ups and the next planned project, including empirical findings about external tools (paths, event schemas, version-specific behavior). When asked to plan or start new work on this repository, read it first. Update it when items land or new ones emerge.

### Agent Dispatch Invocations Use XML Syntax

When documenting agent or subagent dispatch invocations in skills or agent prompts, use XML-style blocks:

```
<invoke name="Task">
<parameter name="subagent_type">ed3d-basic-agents:sonnet-general-purpose</parameter>
<parameter name="description">Brief description of what the subagent does</parameter>
<parameter name="prompt">
The prompt content goes here.

Can be multiple lines.
</parameter>
</invoke>
```

This format keeps the model on-rails better than fenced code blocks with plain text descriptions. It documents agent-dispatch invocations generally.

**Do not** write dispatch invocations as prose like "Use the Task tool with subagent_type X and prompt Y". Use the XML block format.

### Version Updates Require Marketplace and Changelog Sync

When updating a plugin's version in its `.claude-plugin/plugin.json`, you must also:

1. Update the corresponding version in `.claude-plugin/marketplace.json` at the repo root
2. Add a changelog entry to `CHANGELOG.md` at the repo root

Changelog entries go at the top (after the `# Changelog` heading) and follow the format:

```markdown
## [plugin-name] [version]

Brief description of the release.

**New:**
- New features or additions

**Changed:**
- Modifications to existing behavior

**Fixed:**
- Bug fixes
```

Only include sections that apply. Keep entries concise.

The top-level `version` in `.claude-plugin/marketplace.json` is bumped once per catalog change set that adds or changes a package (e.g. 2.1.0 when `ed3d-hook-jj-git-safety` was added, 2.2.0 when `ed3d-completion-summary` was added); plugin entry versions follow the sync rule above independently.

### Copilot-Only Packages

New Copilot-targeted packages follow the `ed3d-hook-jj-git-safety` pattern: a catalog-only `.claude-plugin/plugin.json` manifest (no Claude `hooks.json` registration), explicit-deployment install docs (Copilot CLI reads them and they do not depend on Claude Code), a `copilot-only` catalog keyword, and offline POSIX tests. `ed3d-completion-summary` is the second such package.
