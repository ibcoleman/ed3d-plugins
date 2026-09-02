# Polytoken to Copilot CLI Portability Audit (2026-09-01)

Audit of whether the Polytoken facet and subagent definitions can be carried over to GitHub Copilot CLI. This audit is grounded entirely in local, verified evidence: the six root facet/subagent resources served by the local Polytoken VFS (captured via `polytoken vfs cat` with raw SHA-256 digests), the two immediate transclude dependencies of those roots, the shared evidence parser/validator in `scripts/`, and this repository's own `AGENTS.md` / `ROADMAP.md`. No claim below asserts an external Polytoken source URL: the authoritative source of record is the captured `polytoken://` content and its digests in the companion evidence file.

## Executive answer

Polytoken's facet/subagent execution model ports to Copilot CLI with **partial fidelity**. Four of the twelve capabilities are directly portable (`RESEARCH_DECOMPOSITION`, `SUBAGENT_HANDOFF`, `PLAN_REVIEW_GATE`, `COMPLETION_SUMMARY`); five are portable with re-engineering (`EVIDENCE_CONTRACTS`, `MODEL_TOOL_SKILL_SCOPING`, `ADVERSARIAL_REVIEW`, `CONTEXT_RESUME_STATE`, `OBSERVABILITY`); three are gaps with no faithful equivalent (`FACET_SEPARATION`, `MECHANICAL_ENFORCEMENT`, `TEMPLATING_COMPOSABILITY`). The highest-fidelity MVP is a plan-then-execute custom agent (reusing the existing `plan-reviewer.agent.md` twin) plus re-expressed researcher/plan-reviewer/general-purpose agents with plain-prompt output contracts. One referenced case study, the AirPods portability report, is absent from this checkout and is classified **unresolved** rather than observed.

## Scope, assumptions, and evidence quality

Evidence: 2026-09-01-polytoken-copilot-portability-audit.evidence.json
Roadmap file: ROADMAP.md
Roadmap status: audit complete 2026-09-01; implementation deferred

The audit covers the six root facet/subagent definitions served by the local Polytoken VFS and their immediate transclude dependencies. Assumptions: (1) the local VFS is the source of record -- no external URL is asserted; (2) a claim is *observed* only when it is directly verifiable in captured content or this checkout, and *unresolved* otherwise; (3) no separate AirPods case-study artifact exists in this checkout and the cited VFS URI is unresolved; the audit and ROADMAP necessarily mention the case study because they record that unresolved status, so portability inferences attributed to it are unresolved, not observed. Evidence quality is high for the six roots (full `polytoken vfs cat` output captured and hashed) and lower for the two recursive dependencies, whose full text is not captured.

## Polytoken runtime/workflow model

Polytoken runs a facet-driven loop. The plan facet is read-only: it denies file/shell mutations, permits only the control-plane tools `write_plan` / `edit_plan` / `handoff_plan`, and composes its prompt from transcluded system prompts. The execute facet implements the handed-off plan and calls `complete_goal` when integration is enabled. The orchestrate facet builds a working dependency graph and delegates independent nodes to subagents in the same wave. Subagents (`researcher`, `plan-reviewer`, `general-purpose`) run in isolated contexts with pinned models, scoped tools, and `exit_tool` output contracts. The transclude/Jinja template layer composes system prompts at runtime; `tools_deny` lists, `compaction_hint`s, and session continuation preserve state across handoffs.

The six workflow stages recorded in evidence are:

- Plan facet read-only planning (`polytoken://facets/plan.md`): FACET_PROMPT_COMPOSITION, FACET_MODEL_SELECTION, FACET_TOOL_FILTERING, FACET_SKILL_FILTERING, FACET_PERMISSION_HINT, HOOK_TIMING, HOOK_ENFORCEMENT, FACET_COMPACTION_HINT, SESSION_CONTINUITY, TEMPLATING_RUNTIME, TRANSCLUDE_SEMANTICS
- Execute facet implementation (`polytoken://facets/execute.md`): FACET_TRANSITIONS (transition protocol unresolved)
- Orchestrate facet delegation (`polytoken://facets/orchestrate.md`): SUBAGENT_INVOCATION, SUBAGENT_RESULT_RETURN, SUBAGENT_ISOLATION, SESSION_COMPACTION, SESSION_CLEAR, VFS_INSPECTION
- Researcher evidence gathering (`polytoken://subagents/researcher.md`): WEB_SEARCH, SKILL_LOADING, SUBAGENT_SKILL_ACCESS
- Plan-reviewer gate (`polytoken://subagents/plan-reviewer.md`): SUBAGENT_MODEL_CONFIG
- General-purpose inherit-tools delegate (`polytoken://subagents/general-purpose.md`): SUBAGENT_TOOL_INHERITANCE

## Existing ed3d/Copilot workflow model

This repository targets GitHub Copilot CLI (see AGENTS.md). Copilot CLI composes behavior from custom agents (`agent.md` files with frontmatter), skills, hooks (e.g. `preToolUse`), and slash commands. The repository already ships Copilot-native twins of two Polytoken concepts: `plugins/ed3d-orchestrate/agents/plan-reviewer.agent.md` (severity-classified plan review) and `plugins/ed3d-orchestrate/agents/adversary.agent.md` (adversarial reviewer twin). Separately, the ed3d-orchestrate plugin's check-review-loop and adversary-write-guard hooks provide mechanical write-guard enforcement on the Copilot side. There is no facet or transclude analogue: Copilot replaces prompt composition with agent/skill files.

## Capability-by-capability equivalence matrix

| Capability | Polytoken mechanism | Copilot CLI equivalent | Verdict | Semantic IDs |
|---|---|---|---|---|
| RESEARCH_DECOMPOSITION | orchestrate/execute facets delegate research to a read-only researcher subagent with a success criterion and evidence contract | Copilot custom agents: researcher.agent.md inherits read-only tools | portable | WEB_SEARCH |
| SUBAGENT_HANDOFF | subagent invocation with isolated context; results returned only via exit_tool; resume_from for context carry-over | Copilot subagent lifecycle (task tool) with exit_tool-style structured response | portable | SUBAGENT_INVOCATION, SUBAGENT_RESULT_RETURN |
| EVIDENCE_CONTRACTS | researcher returns summary/files/sources; caller integrates as evidence, not truth | plain-prompt output contract on researcher/plan-reviewer agents | partial | SKILL_LOADING, SESSION_CONTINUITY |
| FACET_SEPARATION | plan/execute/orchestrate facets as distinct prompts with disjoint tool grants and transitions | no facet analogue; requires separate custom agents / contexts | gap | FACET_PROMPT_COMPOSITION, FACET_TRANSITIONS, FACET_MODEL_SELECTION |
| MODEL_TOOL_SKILL_SCOPING | per-agent model pins (default_model:mini/full), tool allow/deny lists, and skills_allow/tag!research scoping | agent frontmatter model + allowed-tools; skills_allow support is unresolved and version-sensitive | partial | SUBAGENT_TOOL_INHERITANCE, SUBAGENT_SKILL_ACCESS, FACET_TOOL_FILTERING, FACET_SKILL_FILTERING |
| PLAN_REVIEW_GATE | plan facet runs the plan-reviewer subagent before handoff_plan and iterates on critical/high findings | plan-then-execute workflow with plan-reviewer.agent.md gate | portable | SUBAGENT_MODEL_CONFIG |
| ADVERSARIAL_REVIEW | plan-reviewer severity ladder (critical/high/medium/low) and test-to-acceptance-criteria audit | adversary.agent.md twin with severity-classified findings | partial | SUBAGENT_ISOLATION |
| MECHANICAL_ENFORCEMENT | tools_deny lists and hook-enforced write guards are mechanical, while `autonomous_hint` is procedural side-effect discipline | preToolUse hooks and protected-skill patterns; weaker denial model | gap | FACET_PERMISSION_HINT, HOOK_TIMING, HOOK_ENFORCEMENT |
| CONTEXT_RESUME_STATE | compaction_hint per facet; session continuation and saved-session goal tracking | session continuity is CLI-managed; compaction hints not exposed | partial | FACET_COMPACTION_HINT |
| COMPLETION_SUMMARY | complete_goal on plan completion; session compaction and clear summaries | session-model-change event + completion summary skill | portable | SESSION_COMPACTION, SESSION_CLEAR |
| TEMPLATING_COMPOSABILITY | Jinja + tag!ALL mechanics and transclude-composed system prompts | skill/agent file composition; no Jinja/tag!ALL or transclude | gap | TEMPLATING_RUNTIME, TRANSCLUDE_SEMANTICS |
| OBSERVABILITY | VFS inspection of facet/subagent definitions; web_search/web_fetch grounding | copilot session-state events.jsonl; VFS inspection has no analogue | partial | VFS_INSPECTION |

## Quality-impact/cost ranking

Ranked by quality impact per unit of porting cost:

1. `RESEARCH_DECOMPOSITION` -- highest impact, lowest cost: a read-only researcher agent is already the Copilot pattern.
2. `PLAN_REVIEW_GATE` -- high impact, low cost: the existing plan-reviewer.agent.md twin is nearly drop-in.
3. `ADVERSARIAL_REVIEW` -- high impact, low cost: adversary.agent.md already ships.
4. `COMPLETION_SUMMARY` -- medium impact, low cost: the completion summary skill already ships.
5. `SUBAGENT_HANDOFF` / `EVIDENCE_CONTRACTS` -- medium impact, medium cost: re-express exit_tool contracts as plain-prompt contracts.
6. `MODEL_TOOL_SKILL_SCOPING` -- medium impact, medium cost: agent frontmatter grants approximate it.
7. `OBSERVABILITY` -- medium impact, medium cost: needs a session watcher over copilot events.jsonl.
8. `CONTEXT_RESUME_STATE` -- low impact, medium cost: no compaction hint analogue.
9. `FACET_SEPARATION`, `MECHANICAL_ENFORCEMENT`, `TEMPLATING_COMPOSABILITY` -- lowest fidelity; gap or defer.

## Case study: research failure and missing controls

The highest-fidelity port (RESEARCH_DECOMPOSITION) is exactly where controls matter most. In Polytoken the researcher returns findings only through `exit_tool` with a success criterion and a scope contract; the caller treats the result as evidence, not truth, and re-verifies consequential claims. A prior portability case study -- the AirPods report -- could not be verified because it is absent from this checkout; treating an absent case study as observed would be a research failure. The missing control here is that no pre-existing mechanical check forced an absent-artifact claim to be marked unresolved; this audit's validator now enforces that status. This audit's evidence schema records that control via the case-study citation status field:

- research delegation failure / missing evidence controls: polytoken://subagents/researcher.md (observed)
- AirPods portability case study: polytoken://case-studies/airpods-portability.md (unresolved)

## Recommended MVP ports, deferred work, and explicit non-goals

**Recommended MVP (in order):**

- **RECOMMENDATION:** Extend existing ed3d-orchestrate with a Copilot plan-then-execute handoff gate (do not duplicate its existing review/adversary gates).
  - benefit: adds the missing operator handoff/approval boundary between plan and builder while reusing the existing plan-reviewer and adversary controls; plan→review→build ordering already exists
  - touched_files: plugins/ed3d-orchestrate/commands/, plugins/ed3d-orchestrate/agents/plan-reviewer.agent.md
  - mechanism: a thin handoff integration around existing ed3d-orchestrate gates, not a second gate implementation
  - testability: hermetic offline tests assert the gate order and the severity-classified findings contract
  - success_measurement: a plan with a critical/high finding cannot reach the execute step; regression test covers it
- **RECOMMENDATION:** Re-express the three subagents as Copilot custom agents with frontmatter tool/model grants.
  - benefit: preserves evidence contracts and model/tool scoping with the least new machinery
  - touched_files: plugins/ed3d-research-agents/agents/, plugins/ed3d-basic-agents/agents/, plugins/ed3d-orchestrate/agents/
  - mechanism: actual agent paths are `plugins/ed3d-research-agents/agents/combined-researcher.agent.md`, `plugins/ed3d-orchestrate/agents/plan-reviewer.agent.md`, and `plugins/ed3d-basic-agents/agents/sonnet-general-purpose.agent.md`; prompts remain prose-only and read-only
  - testability: replay the recorded evidence and validate the regenerated audit with the shared CLI pair
  - success_measurement: both CLIs return clean on the regenerated artifacts; subagent output contracts match the evidence schema

**Deferred (non-MVP):** facet separation, mechanical enforcement via hooks, template/tag!ALL composition, and a session watcher for observability.

**Explicit non-goals for the MVP:** no reimplementation of transclude/Jinja; no multi-facet single-session switching; no hook-based write guard until the CLI hook surface stabilizes.

## Compatibility and version risks

Copilot CLI hook schema and payload behavior are coupled to the installed CLI version and must be re-verified after upgrades. The completion-summary hook depends on `sessionStart` output shape. `skills_allow`/`allowed-tools` frontmatter keys are documented for custom agents and skills but are version-sensitive. The `polytoken://` VFS is a local, versioned source of record: the SHA-256 captured here pins the exact facet/subagent definitions this audit analyzes; re-capturing after a Polytoken upgrade invalidates earlier claims. The roadmap status keyword `idea validated` is recorded in ROADMAP.md and unchanged by this audit.

## Source index

- root-plan-md: polytoken://facets/plan.md
- root-execute-md: polytoken://facets/execute.md
- root-orchestrate-md: polytoken://facets/orchestrate.md
- root-researcher-md: polytoken://subagents/researcher.md
- root-plan-reviewer-md: polytoken://subagents/plan-reviewer.md
- root-general-purpose-md: polytoken://subagents/general-purpose.md
- recursive dependency (facet body): polytoken://system_prompts/facet.md
- recursive dependency (plan shape): polytoken://resources/plan_spec_default.md
- local-AGENTS-md: AGENTS.md
- local-ROADMAP-md: ROADMAP.md
- local-docs-research-2026-09-01-polytoken-copilot-portability-audit-md: docs/research/2026-09-01-polytoken-copilot-portability-audit.md
- local-docs-research-2026-09-01-polytoken-copilot-portability-audit-evidence-json: docs/research/2026-09-01-polytoken-copilot-portability-audit.evidence.json
- local-scripts-portability_evidence_parser-py: scripts/portability_evidence_parser.py
- local-scripts-validate_portability_audit-py: scripts/validate_portability_audit.py
- local-scripts-replay_portability_evidence-py: scripts/replay_portability_evidence.py
- local-scripts-test_validate_portability_audit-py: scripts/test_validate_portability_audit.py
- hooks-ref: https://docs.github.com/en/copilot/reference/hooks-reference
