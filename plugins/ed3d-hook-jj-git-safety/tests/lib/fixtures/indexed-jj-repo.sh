#!/bin/sh
# indexed-jj-repo.sh -- build a REAL git index fixture with a tracked `.jj` path.
#
# The offline suite normally uses bare placeholder repos (`newrepo` creates
# empty `.jj`/`.git` dirs), so the hook's read-only index inspection
# (`git ls-files -- .jj`, `git check-ignore`) finds no tracked jj internals and
# the R_JJ_TRACKED guard can never fire. This fixture instead creates a genuine
# git repository whose index tracks a path under `.jj/`, which lets tests
# exercise the real "jj internal state is tracked or stageable by git" guard
# end-to-end against the actual packaged hook.
#
# Usage:  sh indexed-jj-repo.sh <dest-dir>
#   - creates <dest-dir> as a colocated repo: a real `.git` (git init) with a
#     `.jj/` tree registered in the index; the working tree is left untouched
#     except for the added file, and nothing outside <dest-dir> is mutated.
#   - exits 0 on success. Requires a real `git` on PATH (the hook already needs
#     git for its own index inspection).
#
# POSIX sh only. No remote, no network, no side effects outside <dest-dir>.
set -u

dest="$1"
[ -n "$dest" ] || { echo "indexed-jj-repo: missing dest dir" >&2; exit 2; }

mkdir -p "$dest/.jj/repo/store"
printf 'indexed-jj-fixture\n' > "$dest/.jj/repo/store/data"

if ! (cd "$dest" && git init -q 2>/dev/null); then
    echo "indexed-jj-repo: git init failed in '$dest'" >&2
    exit 1
fi

if ! (cd "$dest" && git add .jj/repo/store/data 2>/dev/null); then
    echo "indexed-jj-repo: git add failed in '$dest'" >&2
    exit 1
fi

# Sanity: the tracked jj path must actually be visible to `git ls-files`.
if [ -z "$(cd "$dest" && git ls-files -- .jj 2>/dev/null | head -n 1)" ]; then
    echo "indexed-jj-repo: .jj not tracked in index of '$dest'" >&2
    exit 1
fi

exit 0
