# v0 acceptance exercises

These exercises validate a candidate, not an old-versus-new comparison. Record
expected outputs before execution. Inspect the actual files and checks, not
just tool exit status. Keep observations sanitized; do not attach raw sessions.

## Invocation under test

Use the README's explicit file-guided session route. The current parent reads
`skills/native-orchestration/SKILL.md` and applies it to each outcome below.
No registry reload, global install, or new CLI process is needed. Record
registry/slash discovery separately; file loading cannot establish it.

## Direct case: package metadata

**Request:** using the candidate instructions, create the catalog-only manifest
for `ed3d-native-orchestration` 0.1.0. Describe a Copilot-only advisory Agent Skill
for direct work, native delegation, and parent integration. Use the repository's
author/license conventions. Include `copilot-only`; register no hooks or agents.

**Expected output:** `.claude-plugin/plugin.json` with the requested name/version,
a nonempty description, author, license, and keywords. Parent writes it directly,
parses the JSON, and inspects the fields. No worker, operator clarification,
installation, or runtime permission change is warranted.

## Multi-stage case: usable candidate package

**Request:** finish the candidate's distribution and acceptance surface. Produce
usage documentation and an offline POSIX package check independently; integrate
both with catalog metadata and repository documentation, then verify the
assembled package and persist it.

**Expected outputs and ownership:**

| Owner | Deliverable | Prerequisites / acceptance |
|---|---|---|
| Documentation worker | `README.md` | Candidate skill and invocation contract. Complete file-guided example; opt-in repo-local instructions; removal boundaries; evidence limitations. No global installation. |
| Check worker | `tests/check-package.sh`, `tests/run.sh` | Package name/layout contract. POSIX shell plus jq; static checks with known positive and negative fixtures before checking the real package. No VCS/network/CLI inference, prompt-semantic score, or runtime simulation. |
| Parent | Manifest, catalog, root README/changelog/roadmap, this record | Preserve prior entries; agree name/version/description/source; integrate returned artifacts, inspect outputs, execute compatible checks, repair consequential gaps. |

The workers have disjoint write ownership. Neither changes the skill or shared
catalog. Parent catalog/documentation work can proceed while both run; final
integration waits for actual results. Workers do not delegate or own approvals.
Use at most these two workers for this exercise, unless a real blocker requires
operator authorization; this is an exercise bound, not a product limit.

**Observe:** useful parent progress between dispatch and results, returned file
ownership, corrections, duplicated work, integration effort, unnecessary operator
interruptions, and any naturally changed dependencies. Do not invent a change.
If no change occurs, say so; the completed shared pilot in #27 supplies earlier
reference evidence, not proof that this packaged skill adapts correctly.

## Evidence record: 2026-10-10

Copilot CLI 1.0.95; separate Jujutsu workspace `ed3d-plugins-native-v0`.
This was the authoring parent's application of the new file-guided instructions,
not a blinded test or a claim that the skill alone caused the behavior.

| Layer | Actual evidence | Limit |
|---|---|---|
| File-guided invocation | Parent explicitly read the new `SKILL.md`, then performed the direct and multi-stage requests above in the live session. | Not skill-tool injection, registry discovery, or slash invocation. |
| Direct output | Parent created the manifest without workers, parsed it with jq, and inspected name, version, description, author, license, keywords, and absence of hook/agent registration. | One small metadata task, not general coding proficiency. |
| Multi-stage output | Two native workers returned the README and two shell check files. Parent updated catalog/root docs while they ran, integrated their files, repaired checker defects, executed the checks, and completed this evidence record. | A bounded package-delivery task, not long-running unattended certification. |
| Static package checks | Shell syntax checks passed. The corrected checker accepted the assembled package and verified manifest/catalog agreement, skill frontmatter/layout, required docs, and root changelog entry. | The frontmatter check supports this package's plain `name`/`description` format, not arbitrary YAML or prose correctness. |
| Offline checker behavior | `sh plugins/ed3d-native-orchestration/tests/run.sh` passed 11 fixture controls and the real-package check. A separate incomplete-repository fixture confirmed the runner exits 1 on integration failure. | Fixture results concern the checker, not model behavior or runtime enforcement. |
| Offline usage recipe | The README's actual copy block produced byte-identical skill content in a disposable repository and refused a second copy without replacing the destination. Temporary files were removed. | No running CLI discovered that temporary copy. |
| Preservation | Jujutsu retained the original workspace revision; the candidate diff contains only the new package and five root integration files. Existing catalog entries compare equal. | No installed-copy integrity audit was attempted; no installation or settings mutation was issued. |
| Optional registry route | Official Copilot documentation supports repo-local skills and reload/info commands. | Not exercised in this session. Source validation cannot substitute for this observation. |

### Corrections and coordination cost

No operator clarification, plan approval, or permission relaxation was requested.
The parent continued catalog and repository-documentation work after the two
dispatches, then collected each result using its returned ID. Workers had
non-overlapping write ownership and did not delegate.

The check worker's positive fixture repeated an incorrect assumption: it put the
changelog inside the package, although the assignment required the root changelog.
The real checker therefore reported a missing file even though the required
root file existed. **The checker was wrong, not the repository.** Its runner
also printed `PENDING` and returned 0 on a real-package failure. Parent execution
reproduced both problems before repair.

The parent corrected the fixture and path, made integration failure nonzero,
and added controls for root-changelog absence, catalog drift, missing
`copilot-only`, catalog runtime registrations, and unsupported frontmatter fields.
The complete positive fixture now passes before negative cases and real-package
validation. A separate runner fixture confirms failure is no longer masked.
No live failure injection or runtime diagnostics were used.

Documentation integration replaced a hypothetical example with a task runnable
against this checkout, added byte comparison after copying, and clarified that
removal/reload cannot erase instructions already in a conversation.

Coordination cost included two assignment/result handoffs, parent artifact review,
checker repairs, and reruns. Parent verification necessarily reread returned
files; it did not repeat either worker's entire assignment. No duplicate worker
assignment or conflicting edit was observed. No agent-to-agent messaging or
worker relaunch was needed.

Integration acquired a real additional prerequisite: repair the checker before
using its success as package evidence. Parent completed this small remainder
directly rather than expanding the worker machinery. This is an observed
integration adjustment, not a cancellation/recovery test. The earlier shared
#27 prerequisite-change observation remains reference evidence, not a test of
this packaged skill.

### Comparison boundary

The candidate can enter a separately authorized matched comparison using its
file-guided entry point. Keep task inputs, permissions, model settings, expected
outputs, and invocation mode comparable. No old-versus-new comparison ran here.

Before comparing the optional registry/slash route, copy only the owned skill
as documented, run `/skills reload`, verify its location with
`/skills info native-orchestration`, and exercise the command actually offered.
That is the remaining action for registry evidence, not a prerequisite to the
demonstrated file-guided route.

Sustained execution across long tasks/context transitions, durable resume,
cancellation, enforcement, and speed/cost benefits remain unverified. The
completed shared pilots were reused as context rather than rerun. #26 stays
deferred; no new runtime guarantee or cross-team technical design is inferred.
