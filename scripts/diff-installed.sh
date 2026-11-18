#!/usr/bin/env bash
# Compare a plugin's source with the copy Copilot CLI installed.
# Usage: scripts/diff-installed.sh [plugin-name ...]   (default: ed3d-orchestrate)
# Env:   COPILOT_INSTALLED_PLUGINS (default ~/.copilot/installed-plugins/ed3d-plugins)
# Exit:  0 when every named plugin matches, 1 on any difference, 2 when a copy is missing.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
installed_root="${COPILOT_INSTALLED_PLUGINS:-$HOME/.copilot/installed-plugins/ed3d-plugins}"
plugins=("$@")
[ "${#plugins[@]}" -gt 0 ] || plugins=(ed3d-orchestrate)

status=0
for name in "${plugins[@]}"; do
  source_dir="$repo_root/plugins/$name"
  installed_dir="$installed_root/$name"
  for dir in "$source_dir" "$installed_dir"; do
    if [ ! -d "$dir" ]; then
      echo "MISSING $name: $dir" >&2
      exit 2
    fi
  done
  if diff -r -q --exclude=__pycache__ --exclude='*.pyc' "$source_dir" "$installed_dir"; then
    echo "MATCH $name: $installed_dir"
  else
    echo "DIFFERS $name: run 'diff -r $source_dir $installed_dir' for details" >&2
    status=1
  fi
done
exit "$status"
