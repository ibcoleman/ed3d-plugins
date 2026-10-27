# ed3d-native-orchestration

An advisory Agent Skill for GitHub Copilot CLI. It helps choose between doing
work directly and useful native delegation, while keeping integration and
verification with the parent session.

This package contains one reusable skill. It has no hooks, runtime service, or
installer. The `.claude-plugin/plugin.json` file is catalog metadata; it does
not install or register the skill. No published release is implied.

## Use it from this checkout

The default route needs no copy or registry setup. In an existing trusted
Copilot CLI session rooted in this workspace, give a concrete request such as:

> Read `plugins/ed3d-native-orchestration/skills/native-orchestration/SKILL.md`
> and apply its instructions to summarize this package's manifest at
> `plugins/ed3d-native-orchestration/.claude-plugin/plugin.json`.
> Return its name, version, and whether it registers hooks or agents.
> Read only these two files. Do not edit files or install anything.

Replace the example outcome and deliverables with your actual task. State
boundaries such as permitted files, commands, or side effects. The session can
read the skill file and apply its guidance to the current request.

This is file-guided use. It is not skill-registry injection, and it does not
make a slash command discoverable. The skill is guidance, not a runtime
enforcement mechanism.

## Optional repo-local skill discovery

To opt in to Copilot CLI's repo-local skill discovery, copy the skill to
`.github/skills/native-orchestration/SKILL.md` from the repository root. Do this
only in a trusted workspace. First check that `.github` and `.github/skills`
are not symlinks; if either is a symlink, stop and resolve the destination
yourself. Create the destination exclusively so an existing directory,
symlink, or file is never overwritten:

```sh
set -eu
source=plugins/ed3d-native-orchestration/skills/native-orchestration/SKILL.md
dest=.github/skills/native-orchestration

if [ -L .github ] || [ -L .github/skills ]; then
  printf '%s\n' 'refusing symlinked skill parent' >&2
  exit 1
fi
if [ -L "$source" ] || [ ! -f "$source" ]; then
  printf '%s\n' 'skill source is missing' >&2
  exit 1
fi
mkdir -p .github/skills
if ! mkdir "$dest"; then
  printf '%s\n' 'destination already exists; nothing copied' >&2
  exit 1
fi
cp -n "$source" "$dest/SKILL.md"
cmp "$source" "$dest/SKILL.md"
```

`mkdir "$dest"` fails rather than replacing a pre-existing destination, and
`cp -n` avoids replacing a file that appears there later; `cmp` verifies that
the destination actually matches the source rather than trusting the copy's
exit status. These copy instructions assume `cp -n` is available (Linux,
macOS, or WSL). If the copy or comparison fails, inspect the directory before
taking action; remove it only if you created it and it contains no other files.

Then reload skills and verify the discovered location in the same Copilot CLI
session:

```text
/skills reload
/skills info native-orchestration
```

Confirm that the reported location is
`.github/skills/native-orchestration/SKILL.md`. If the runtime offers a slash
invocation after discovery, use the exact command it displays. Do not assume
that a command exists before discovery or derive one from the folder name.

GitHub's current instructions for project skills are at
[Create skills for Copilot CLI](https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/create-skills).

### Remove only your repo-local copy

If you created this exact destination and want to remove it, first confirm
that the parent directories and destination are still your non-symlinked
directories. Remove only its skill file, then remove the directory only if empty:

```sh
rm .github/skills/native-orchestration/SKILL.md
rmdir .github/skills/native-orchestration
```

`rmdir` leaves the directory in place if it contains anything else. Do not
remove neighboring skills, edit global settings, or change authentication.
If you did not create the copy, coordinate with its owner instead.
Reload skills and confirm this location is no longer listed. Start a fresh
session if already-loaded instructions must no longer apply; deleting their
source cannot remove text already present in the current conversation.

## What the guidance covers

- Keep small tasks and tightly coupled work in the parent session.
- Delegate bounded work when separate context, specialization, or independent
  progress is useful; do not delegate just to create activity.
- Give a worker clear ownership, allowed reads and writes, acceptance evidence,
  and a compact return contract. Keep shared integration with the parent.
- Inspect returned work, integrate it, and run checks that support the final
  claim. A worker's report alone does not establish success.
- Preserve operator approval boundaries. The skill grants no permissions;
  route approval needs and material decisions to the parent.

The configured Copilot model defaults remain controlled by the host and its
configuration. This skill does not select or enforce a model. It also does not
guarantee enforcement, cancellation, resumption, unattended completion, or
speed or cost improvements.

## Comparing with ed3d-orchestrate

Both plugins can remain installed; choose one workflow per fresh session.
Use separate sibling workspaces with no inherited active
`.ed3d/orchestrate-state.json`, including in ancestor directories. The existing
`ed3d-orchestrate` write guard, when enabled, can block any subagent's edits
during an active PENDING review in that workspace; it cannot distinguish this
workflow's workers. This candidate adds no competing hook or review state.
Plugin discovery and real-world comparisons still require live verification.

## Offline package check

From the repository root, run:

```sh
sh plugins/ed3d-native-orchestration/tests/run.sh
```

The check requires a POSIX shell and `jq`. It checks static package properties
using fixture controls. It does not test live model behavior, skill discovery,
slash-command availability, or task outcomes. No result is claimed here; run
the command in your environment and inspect its output.

For the acceptance scenarios and evidence boundaries, see
[tests/acceptance.md](tests/acceptance.md).
