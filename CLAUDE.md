# ed3d-plugins

Claude Code plugins for design, implementation, and development workflows.

## Conventions

### Task Invocations Use XML Syntax

When documenting Task tool invocations in skills or agent prompts, use XML-style blocks:

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

This format keeps the model on-rails better than fenced code blocks with plain text descriptions.

**Do not** write Task invocations as prose like "Use the Task tool with subagent_type X and prompt Y". Use the XML block format.

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

### Retrospective Document Convention

Last verified: 2026-03-25

The `/retrospective` skill produces structured markdown documents at `docs/design-plans/{slug}-retrospective.md`. These documents capture lessons learned when a development attempt hits a dead end.

**Producer:** `retrospective` skill (writes the document)

**Consumers:** `brainstorming` and `starting-a-design-plan` skills (read the document to inform new design attempts)

**File location contract:** `docs/design-plans/{slug}-retrospective.md`, where `{slug}` is derived from the design plan filename or sanitized branch name. Collision avoidance uses a counter suffix (`-2`, `-3`, etc.).

**Required sections consumed by downstream skills:**
- `Recommendations for Next Attempt` -- pre-populated as constraints for new designs
- `Assumption Audit` -- "Invalidated" assumptions are flagged so new designs avoid them
- `What Worked` -- validated approaches are seeded into new design exploration

**Invariant:** Any skill that produces design plans or brainstorming output must check for retrospective documents in `docs/design-plans/` before starting its design work. Currently this applies to `brainstorming` (Phase 1) and `starting-a-design-plan` (between Phase 1 and Phase 2).
