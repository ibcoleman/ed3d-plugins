# Implementation Plan: Pinned Dispatch with Auto Fallback

## Goal

Restore preferred model/effort dispatch for model-selectable Copilot accounts while preserving operation on Auto-only accounts. The fallback remains procedural because Copilot CLI exposes no stable plugin-level dispatch-result/retry API. This is a conservative protocol change, not a new hook/API integration.

## Requirements

1. Keep all Copilot-native `*.agent.md` frontmatter model-free; direct agent launches remain Auto-compatible.
2. On each orchestrated delegated-agent dispatch, make a pinned-first preferred attempt:
   - adversary and plan-reviewer: `kimi-k3` / `high`
   - builders and fixers: `gpt-5.6-luna` / `medium`
   - scouts: `gpt-5.6-luna` / `low`
3. If and only if Copilot visibly reports an explicit **pre-start** rejection for model, account, or effort availability, make one fallback attempt with both `model` and `reasoning_effort` omitted.
4. Preserve the exact agent, task prompt, plan path, working directory, and role on fallback. The only changed dispatch inputs are the two omitted overrides.
5. Distinguish dispatch outcomes conservatively: an explicit pre-start rejection may trigger the fallback; an ambiguous refusal is terminal and is reported without retry; a started dispatch with no verdict follows the existing protocol-failure path and never changes to model fallback.
6. Report preferred success, fallback reason and retry, fallback result, protocol failure, or ambiguous refusal prominently. The existing state schema, nonce, review history, resume, write-guard, and safety-cap behavior remain unchanged.
7. Every named `*.agent.md` resource is invoked through native agent/subagent delegation, never the Skill loader.

## Retry classification and composition

The implementation must encode these rules in each dispatch-bearing skill and in the static checks:

- **Explicit pre-start model/account/effort rejection:** classify only a visible rejection that occurs before any start signal and explicitly identifies model, account availability, or effort support. It consumes the one model fallback and retries once with both `model` and `reasoning_effort` omitted.
- **Rate limit:** use the existing wait, retry-once, then serialize/small-batch behavior. A rate-limit transport retry does not consume the model fallback and does not change the selected model/effort policy.
- **Started/no-verdict:** use the existing protocol-failure path (record the protocol failure and perform at most its existing one protocol re-dispatch, if that path calls for it), preserving the current selection mode. Never invoke a model fallback after a start signal.
- **Ambiguous/no-start outcome:** do not retry; report the ambiguity to avoid duplicate work. It is not evidence of model incompatibility.
- **Attempt ceiling:** a dispatch lineage has at most three semantic submissions: preferred, at most one Auto fallback, and at most one protocol-failure re-dispatch. Transport rate-limit retries are not semantic submissions and remain governed by the existing rate-limit rule. A rejection of the fallback is terminal; there is no second fallback.
- **No duplicate rule:** never issue the same fallback twice, never combine a protocol retry with a new model fallback, and never retry an ambiguous outcome. A protocol-failure re-dispatch is the sole separately named exception: it must preserve the original prompt, agent, role, working directory, and current selection mode (including Auto after an Auto fallback), and it is not reported as a fallback.

## Research basis

- Current skills are prose-driven; no structured task wrapper exists in the plugin.
- Current hooks cover write-class preToolUse and stop events, not dispatch rewriting.
- Official Copilot CLI docs document `task`/agent delegation but not a stable request schema, rejection envelope, idempotency contract, or safe retry output contract.
- Observed failure: `Reasoning effort 'medium' is not supported for model 'claude-haiku-4.5'`.
- Therefore implementation must instruct the orchestrator conservatively rather than add an unverified hook/API assumption.

## Implementation Plan

### Phase 1: Dispatch protocol skills

Modify:

- `plugins/ed3d-orchestrate/skills/scout-sweep/SKILL.md`
- `plugins/ed3d-orchestrate/skills/orchestrating-the-loop/SKILL.md`
- `plugins/ed3d-orchestrate/skills/adversarial-review/SKILL.md`

Add one explicitly bounded dispatch protocol section to each skill, delimited with the same literal markers (for example, `<!-- DISPATCH-PROTOCOL:BEGIN -->` and `<!-- DISPATCH-PROTOCOL:END -->`). Each section contains the role's preferred literals, the classification rules above, the exact fallback omission rule, the attempt ceiling/no-duplicate rule, mandatory report wording, full response transparency, and native agent/subagent delegation wording.

The six current no-model policy needles are replaced explicitly as follows:

| Skill | Current no-model needle | Replacement |
|---|---|---|
| `adversarial-review/SKILL.md` | `Use the account's Auto/default model selection` | A bounded pinned-first protocol naming `kimi-k3` / `high`, followed by the explicit-rejection-only Auto fallback |
| `adversarial-review/SKILL.md` | `Do not select a model or set an effort override` | A bounded instruction to select preferred model `kimi-k3` and effort `high` on the preferred attempt, then omit both overrides only on the defined fallback |
| `orchestrating-the-loop/SKILL.md` | `leaving model selection to the account's Auto/default` | A bounded pinned-first protocol naming `gpt-5.6-luna` / `medium` for builders/fixers and `kimi-k3` / `high` for review dispatches, with Auto fallback |
| `orchestrating-the-loop/SKILL.md` | `Do not select or pin a model in dispatch instructions` | A bounded instruction to send the role's preferred `model` and `reasoning_effort`, with both omitted only for the one explicit-rejection fallback |
| `scout-sweep/SKILL.md` | `Use the account's Auto/default model selection` | A bounded pinned-first protocol naming `gpt-5.6-luna` / `low`, followed by the explicit-rejection-only Auto fallback |
| `scout-sweep/SKILL.md` | `Send no model or effort override` | A bounded instruction to select preferred model `gpt-5.6-luna` and effort `low` on the preferred attempt, then omit both overrides only on the defined fallback |

These are replacements, not additions. All unrelated protocol needles in `scripts/validate_plugins.py` remain verbatim, including verdict/state atomicity, history schema, nonce, write-guard, resume, git-baseline, and native-delegation needles. The six listed no-model needles are intentionally removed and replaced. The validator/test must evaluate old-needle absence across the combined text of all three skills, so an old phrase moved from one skill to another still fails.

Add these explicit site-level replacement needles in addition to the six general replacements:

| Exact site | Required replacement needle |
|---|---|
| `adversarial-review/SKILL.md`, primary adversary dispatch near line 55 | A pinned-first `adversary` dispatch using the shared bounded protocol: preferred `kimi-k3` / `high`, then one Auto fallback omitting both overrides only after an explicit pre-start model/account/effort rejection, preserving the exact review prompt, plan path, SHAs, nonce, prior issues, role, and working directory; rate-limit and protocol-failure handling remain separate. |
| `adversarial-review/SKILL.md`, current FIX-FIRST `task-bug-fixer` dispatch near line 101 | A pinned-first `task-bug-fixer` dispatch using the shared bounded protocol: preferred `gpt-5.6-luna` / `medium`, then one Auto fallback omitting both overrides only after an explicit pre-start model/account/effort rejection, preserving the exact fixer prompt, findings, role, path, and working directory; rate-limit and protocol-failure handling remain separate. |
| `orchestrating-the-loop/SKILL.md`, current Phase 4 `task-implementor-fast` dispatch near line 118 | A pinned-first `task-implementor-fast` dispatch using the same shared bounded protocol: preferred `gpt-5.6-luna` / `medium`, then one Auto fallback omitting both overrides only after an explicit pre-start model/account/effort rejection, preserving the exact implementation prompt, task, plan path, role, and working directory; rate-limit and protocol-failure handling remain separate. |

The new focused test must require these three site-specific needles and fail if any old no-model dispatch remains at its site; do not satisfy the check merely by adding a protocol section elsewhere in the skill. Add an explicit cross-skill negative test over the combined raw text of `scout-sweep/SKILL.md`, `orchestrating-the-loop/SKILL.md`, and `adversarial-review/SKILL.md`: reject every residual old-policy dispatch sentence, including `without model or effort parameters`, `without model or effort overrides`, `leave model selection unset`, and `account/CLI defaults decide both` (as well as the six enumerated old needles). The test must fail if any listed old no-model dispatch phrase or sentence remains anywhere in the three skills, even when moved across the former dispatch sites; test the absence, not merely replacement at expected line locations.

Keep direct agent frontmatter unchanged and model-free.

### Phase 2: Validation and documentation

Modify:

- `scripts/validate_plugins.py`
- `plugins/ed3d-orchestrate/README.md`
- `ROADMAP.md`
- `CHANGELOG.md`
- `plugins/ed3d-orchestrate/.claude-plugin/plugin.json`
- `.claude-plugin/marketplace.json`

Add the new focused static test:

- `scripts/test-dispatch-protocol.py` (new file; the `scripts/` directory already exists)

Validator changes must use concrete scoping rather than a repository-wide exception:

1. Keep `model:`, `reasoning_effort:`, `effort:`, and `effortLevel:` forbidden everywhere in all six existing strict orchestrate markdown targets (`ORCHESTRATE_STRICT_MD`): the three skills, both agent files, and `commands/orchestrate.md`. Scan each target's complete raw text, including frontmatter, bounded sections, and prose; do not whitelist a whole file or an unbounded paragraph. Also keep `gemini-3.5-flash`, `Always pin`, and `pinned model` forbidden everywhere in each of those six targets.
2. Define the exact begin/end dispatch markers once. Parse each skill as lines, locate exactly one non-nested bounded section, reject a missing, duplicated, reversed, or overlapping marker pair, and inspect the section body separately from the prefix/suffix.
3. Scope preferred-literal validation to dispatch override syntax/phrases inside the bounded section: require the role-specific combinations (`kimi-k3` with `high`, `gpt-5.6-luna` with `medium` or `low`) there, and reject the model literals outside those sections. Do not globally search for bare `high`, `medium`, or `low`, and do not treat severity labels such as `critical/high` or `medium/low` as effort overrides. Effort validation must match an override phrase/context, never a bare word; the four forbidden key forms above remain unconditional raw-text checks.
4. Require the six replacement protocol needles and reject the six old no-model needles across the combined contents of all three skills (assert each old needle's total cross-file occurrence count is zero, rather than checking only its formerly associated file). Also reject residual old-policy dispatch phrases across that combined text, including `without model or effort parameters`, `without model or effort overrides`, `leave model selection unset`, and `account/CLI defaults decide both`; the test must fail if any old no-model dispatch sentence remains anywhere in the three skills. Also require the three explicit dispatch-site needles in the table below. Check that unrelated protocol needles retain their exact existing strings; do not replace or silently weaken those checks.
5. Require the explicit pre-start classifier, one-fallback rule, both-overrides-omitted fallback, rate-limit non-consumption rule, started/no-verdict protocol-failure rule, ambiguity/no-duplicate rule, three-submission ceiling, preferred/fallback reporting, and agent-vs-Skill-loader distinction.
6. Continue forbidding model frontmatter in all Copilot twins and continue forbidding agent names sent to the Skill loader.

README changes must **replace, not add to**, the existing claims in all three relevant areas: (a) the **Agents and model selection** introduction/table, replacing universal Auto/default rows with the pinned-first role mapping and explicit-rejection-only Auto fallback; (b) **Model and effort defaults**, replacing the claims that no model configuration is required and that omission is the compatibility policy with the best-effort hard-coded IDs, conservative fallback, and model-selectable/Auto-only behavior; and (c) the relevant **Known Limitations** model-selection claim, replacing its statement that selection is universally inherited from Auto/default. Explain pinned-first as best-effort hard-coded model IDs with conservative Auto fallback, not a mechanically intercepted runtime feature; add the observed claude-haiku-4.5 medium-effort rejection and unknown dispatch-error semantics. Add this explicit limitation: preferred-vs-fallback provenance is transcript/report-only and does not survive `/clear` or resume; the existing state schema is not extended to persist it. Do not leave the old Auto-only omission claims alongside the replacement text.

ROADMAP changes must update the existing “Model-id verification — superseded by 0.3.4” follow-up: catalog verification remains dormant while no future catalog/API/operator verification event has occurred. Reactivate that verification only after such a future event confirms that explicit model selection is available again; this plan's prose pins, validator needles, or release do not count as catalog/API/operator verification. Do not claim that hard-coded IDs are catalog-verified by this plan.

Decide and apply the release as `0.3.5 -> 0.4.0`: synchronize `plugins/ed3d-orchestrate/.claude-plugin/plugin.json`, the matching `ed3d-orchestrate` entry in `.claude-plugin/marketplace.json`, and a new top `CHANGELOG.md` entry. Do not leave a conditional “unless patch release” option in the implementation.

## Test Strategy

Add deterministic static checks in `scripts/test-dispatch-protocol.py` covering at minimum:

- `test_preferred_attempt_is_bounded_and_role_specific`;
- `test_six_no_model_needles_are_replaced` (including cross-file old-needle absence and all three site-level dispatch needles);
- `test_no_residual_old_policy_dispatch_phrases` (negative coverage across all three skills, including `without model or effort parameters/overrides`, `leave model selection unset`, and `account/CLI defaults decide both`; fail if any old no-model dispatch sentence remains);
- `test_unrelated_protocol_needles_are_verbatim`;
- `test_override_keys_are_forbidden_everywhere`;
- `test_preferred_literals_are_scoped_to_protocol_sections` (override syntax/phrases only, not bare effort words or severity labels);
- `test_explicit_rejection_has_one_auto_fallback`;
- `test_rate_limit_does_not_consume_fallback`;
- `test_started_no_verdict_uses_protocol_failure_without_model_fallback`;
- `test_attempt_ceiling_and_no_duplicate_rule`;
- `test_preferred_fallback_reporting_and_loader_distinction`;
- `test_version_readme_roadmap_sync`.

Run manually, like the existing standalone suites (the new test is not assumed to be wired into an automatic runner):

- `python3 scripts/test-dispatch-protocol.py`
- `python3 scripts/validate_plugins.py`
- `python3 plugins/ed3d-orchestrate/hooks/test-check-review-loop.py`
- `python3 plugins/ed3d-orchestrate/hooks/test-adversary-write-guard.py`
- `git diff --check`

Optionally record automatic-runner wiring for `scripts/test-dispatch-protocol.py` as a deferred follow-up; it is not part of this implementation.

## Documentation Strategy

Implement README and ROADMAP edits as replacements of the identified stale claims, not additions, and verify those replacements in `test_version_readme_roadmap_sync`. Keep the changelog/version synchronization and the transcript/report-only provenance limitation explicit.

## Acceptance Criteria

Each criterion maps to a named static or existing check:

- **AC.1 — `test_preferred_attempt_is_bounded_and_role_specific`:** all three dispatch skills contain one bounded pinned-first section with the correct role/model/effort mapping, while Copilot agent frontmatter remains model-free.
- **AC.2 — `test_six_no_model_needles_are_replaced`, `test_no_residual_old_policy_dispatch_phrases`, and `test_unrelated_protocol_needles_are_verbatim`:** the six enumerated no-model needles and all listed residual old-policy dispatch phrases are absent across all three skills, the three site-specific adversary/task-bug-fixer/task-implementor-fast dispatches use the shared pinned-first/fallback protocol, and unrelated policy/protocol needles remain byte-for-byte present.
- **AC.3 — `test_override_keys_are_forbidden_everywhere` and `test_preferred_literals_are_scoped_to_protocol_sections`:** all four override-key forms plus `gemini-3.5-flash`, `Always pin`, and `pinned model` are rejected in every strict target, while preferred model/effort validation is limited to override syntax/phrases inside explicitly parsed dispatch sections and does not reject bare effort words or severity labels.
- **AC.4 — `test_explicit_rejection_has_one_auto_fallback`, `test_rate_limit_does_not_consume_fallback`, and `test_started_no_verdict_uses_protocol_failure_without_model_fallback`:** retry classification and composition match the required conservative rules.
- **AC.5 — `test_attempt_ceiling_and_no_duplicate_rule`:** each dispatch lineage has no more than three semantic submissions, has at most one model fallback, and never duplicates an ambiguous/start outcome outside the named protocol-failure path.
- **AC.6 — `test_preferred_fallback_reporting_and_loader_distinction`:** reports identify preferred/fallback/protocol-failure/ambiguous outcomes and every named agent uses native delegation rather than the Skill loader.
- **AC.7 — `test_version_readme_roadmap_sync`:** version is 0.4.0 in both manifests and changelog, README replaces the three stale Auto-only claims and states transcript/report-only provenance that does not survive clear/resume, and ROADMAP keeps catalog verification dormant until a future catalog/API/operator verification event (the plan's prose pins do not qualify) and then names reactivation as the next action.
- **AC.8 — existing hook suites and `scripts/validate_plugins.py`:** review-loop, write-guard, frontmatter, marketplace, and existing orchestration protocol checks pass without implementation-file changes beyond the planned validator/test/documentation work.

## Review Strategy

Run the focused protocol test first, then the repository validator and both existing hook suites. Review the diff manually against the six-needle table and the marker parser rules; inspect the negative cases (old needles, override keys outside sections, preferred literals in an agent/command, rate-limit fallback accounting, and started/no-verdict behavior). Have the plan reviewer/adversary verify both model-selectable and Auto-only paths, especially that the fallback is prose-guided and not represented as an undocumented runtime interception.

## Risks

- **Model catalog drift:** `kimi-k3` and `gpt-5.6-luna` are best-effort hard-coded literals, not a catalog guarantee. Mitigation is the explicit pre-start Auto fallback; catalog probing/ID resolution is a non-goal until explicit selection returns and ROADMAP verification is reactivated.
- **Unstable dispatch result shapes:** Copilot may not expose a stable rejection envelope or start signal. The protocol therefore requires visible evidence, treats ambiguity as terminal, and forbids speculative retries.
- **Prompt/protocol drift:** future edits could move literals outside the bounded section or reintroduce no-model policy text. Marker parsing plus exact positive/negative needles and the focused test provide fail-closed static detection.
- **Duplicate work:** retries after a start signal can duplicate side effects. The attempt ceiling, selection-preserving protocol-failure path, and no-duplicate rule limit this risk; ambiguity never triggers fallback.
- **Context handoff:** preferred-vs-fallback provenance is intentionally not state, so it is lost across clear/resume. The operator-facing transcript/report is the audit surface; no state schema change is introduced.
- **Rate limits:** pinned-first parallelism can still hit provider limits. Existing wait/retry/serialize behavior remains authoritative and is kept separate from model fallback accounting.
