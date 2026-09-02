#!/bin/sh
# test-scope.sh -- verifies the jj-git-safety hook's SCOPE boundaries.
#
# Scope properties verified:
#   - only the `bash` tool is intercepted; every other tool passes through
#   - repo discovery walks up from an arbitrary nested cwd
#   - non-repo and out-of-tree contexts are handled conservatively
#   - defensive nets (compound, wrappers, redirection) apply within bash
#   - the hook NEVER mutates the repository and NEVER contacts a remote
#
# Fully offline: real hook + state-driven `jj` stub + local jq, temp sandbox.
set -u

. "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)/lib/harness.sh"

t_plan 33

clean_repo() {
    mksandbox
    REPO="$SANDBOX/repo"
    newrepo "$REPO" both
    JJ_STUB_ROOT="$REPO"; JJ_STUB_BOOKMARK=1
    unset JJ_STUB_CONFLICTS
    export JJ_STUB_ROOT JJ_STUB_BOOKMARK
}
run_cmd() { mkpayload_obj "$SANDBOX/p.json" "$REPO" bash "$1"; run_hook "$SANDBOX/p.json" tools; }

# ---------------------------------------------------------------------------
# matcher scope: only `bash`
# ---------------------------------------------------------------------------
test_bash_only_scope() {
    clean_repo
    for tool in Read Write Edit Delete Glob Agent MultiEdit; do
        mkpayload_obj "$SANDBOX/p.json" "$REPO" "$tool" "rm -rf / && git push -f"
        run_hook "$SANDBOX/p.json" tools
        t_eq "$__decision" "allow" "scope: tool '$tool' never intercepted"
    done
    mkpayload_obj "$SANDBOX/p.json" "$REPO" bash "rm -rf /"
    run_hook "$SANDBOX/p.json" tools
    t_eq "$__decision" "deny" "scope: bash tool is intercepted"
}

# ---------------------------------------------------------------------------
# nested repo discovery (walk up for .jj / .git)
# ---------------------------------------------------------------------------
test_nested_discovery() {
    mksandbox
    REPO="$SANDBOX/repo"
    newrepo "$REPO" both
    mkdir -p "$REPO/a/b/c/d"
    JJ_STUB_ROOT="$REPO"; JJ_STUB_BOOKMARK=1; unset JJ_STUB_CONFLICTS
    export JJ_STUB_ROOT JJ_STUB_BOOKMARK
    mkpayload_obj "$SANDBOX/p.json" "$REPO/a/b/c/d" bash "git status"
    run_hook "$SANDBOX/p.json" tools
    t_eq "$__decision" "allow" "nested: deep cwd discovers repo, read-only git allowed"
    mkpayload_obj "$SANDBOX/p.json" "$REPO/a/b/c/d" bash "git add ."
    run_hook "$SANDBOX/p.json" tools
    t_eq "$__decision" "deny" "nested: deep cwd, git add denied"
    t_eq "$__reason" "jj-preflight: git mutating/staging operation in a jj-managed repo" \
        "nested: deep cwd -> R_GIT_MUTATE"
}

# ---------------------------------------------------------------------------
# non-repo / out-of-scope directories
# ---------------------------------------------------------------------------
test_non_repo_scope() {
    mksandbox
    NR="$SANDBOX/deep/out/of/repo"; mkdir -p "$NR"
    unset JJ_STUB_ROOT JJ_STUB_BOOKMARK JJ_STUB_CONFLICTS
    mkpayload_obj "$SANDBOX/p.json" "$NR" bash "cat file"
    run_hook "$SANDBOX/p.json" tools
    t_eq "$__decision" "allow" "nonrepo: read-only non-vcs allowed"
    mkpayload_obj "$SANDBOX/p.json" "$NR" bash "jj log"
    run_hook "$SANDBOX/p.json" tools
    t_eq "$__reason" "jj-preflight: no jj or git repository found for command target" \
        "nonrepo: vcs command -> R_NON_REPO"
}

# ---------------------------------------------------------------------------
# defensive nets within bash scope
# ---------------------------------------------------------------------------
test_defensive_nets() {
    clean_repo
    # commands the hook must deny within bash scope
    for c in "git add . && git commit" "echo a; echo b" "rm -rf /" \
             "git push origin main" "git reset --hard"; do
        run_cmd "$c"
        t_eq "$__decision" "deny" "net: '$c' denied"
    done
    # read-only commands the hook deliberately lets through (real behavior)
    run_cmd "echo \$HOME"
    t_eq "$__decision" "allow" "net: read-only 'echo \$HOME' allowed"
    run_cmd "cat file"
    t_eq "$__decision" "allow" "net: read-only 'cat file' allowed"
    run_cmd "printf 'x' > /tmp/f"
    t_eq "$__reason" "jj-preflight: compound or wrapped command with unsafe component" \
        "net: write redirection -> R_COMPOUND"
    run_cmd "nohup cat x"
    t_eq "$__reason" "jj-preflight: compound or wrapped command with unsafe component" \
        "net: nohup wrapper -> R_COMPOUND"
}

# ---------------------------------------------------------------------------
# no repository mutation
# ---------------------------------------------------------------------------
test_no_repository_mutation() {
    mksandbox
    repo="$SANDBOX/repo"; mkdir -p "$repo/.jj" "$repo/.git" "$repo/data"
    printf '%s' 'immutable repository content' > "$repo/data/a.md"
    printf '%s' 'state marker' > "$repo/state.md"
    JJ_STUB_ROOT="$repo"; JJ_STUB_BOOKMARK=1; unset JJ_STUB_CONFLICTS
    export JJ_STUB_ROOT JJ_STUB_BOOKMARK
    snapshot() {
        ( cd "$repo" && find . -type f | sort ) | cksum
        ( cd "$repo" && find . -type f -exec cksum {} \; ) | cksum
    }
    before="$(snapshot)"
    for c in "git add ." "git push -f origin main" "jj rebase -b @"; do
        mkpayload_obj "$SANDBOX/p.json" "$repo" bash "$c"
        run_hook "$SANDBOX/p.json" tools
    done
    after="$(snapshot)"
    t_eq "$after" "$before" "scope: repository tree unchanged after denied ops"
}

# ---------------------------------------------------------------------------
# no remote traffic. With the stub's remote guard armed (JJ_STUB_REMOTE=1),
# any invocation that is NOT a read-only metadata query (root/log/bookmark) is
# reported as REMOTE-CALLED. The hook only ever asks jj for those queries, so
# even for network-touching commands it must never cause a remote invocation.
# ---------------------------------------------------------------------------
test_no_remote() {
    clean_repo
    JJ_STUB_REMOTE=1; export JJ_STUB_REMOTE
    for c in "git push -f origin main" "jj git push --force" "git pull origin" \
             "jj git fetch" "git push --force-with-lease origin main"; do
        run_cmd "$c"
        t_not_contains "REMOTE-CALLED" "$(cat "$SANDBOX/err" 2>/dev/null)" \
            "remote: '$c' -> hook never invoked a network op (stderr)"
        t_not_contains "REMOTE-CALLED" "$(cat "$SANDBOX/out" 2>/dev/null)" \
            "remote: '$c' -> hook never invoked a network op (stdout)"
    done
    unset JJ_STUB_REMOTE
}

# ---------------------------------------------------------------------------
test_bash_only_scope
test_nested_discovery
test_non_repo_scope
test_defensive_nets
test_no_repository_mutation
test_no_remote

cleanup_sandbox
t_done
