#!/bin/sh
# test-jj-preflight.sh -- verifies the EXACT preToolUse contract of the
# Copilot CLI command hook plugins/ed3d-hook-jj-git-safety/hooks/jj-preflight.sh.
#
# Fully offline: it runs the real hook against temp sandbox repos using a
# state-driven `jj` stub and the local `jq` binary. No remote is contacted and
# nothing outside the sandbox is mutated.
#
# Every expected decision/reason below was validated empirically against the
# real hook and is frozen here as the contract.
set -u

. "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)/lib/harness.sh"

t_plan 332

# A clean colocated (jj+git) repo with an attached bookmark, held in globals
# REPO / SANDBOX. NOT called under command substitution: mksandbox must run in
# the current shell so SANDBOX persists.
clean_repo() {
    mksandbox
    REPO="$SANDBOX/repo"
    newrepo "$REPO" both
    JJ_STUB_ROOT="$REPO"
    JJ_STUB_BOOKMARK=1
    unset JJ_STUB_CONFLICTS
    export JJ_STUB_ROOT JJ_STUB_BOOKMARK
}

# run_cmd <command...>  -- object-form payload against the current REPO
run_cmd() {
    mkpayload_obj "$SANDBOX/p.json" "$REPO" bash "$1"
    run_hook "$SANDBOX/p.json" tools
}

# ===========================================================================
# exact contract: stdout JSON shape, allow vs deny, rc always 0
# ===========================================================================
test_contract_shape() {
    clean_repo
    run_cmd "git status"
    t_eq "$__rc" "0"        "contract: hook always exits 0 on a handled decision"
    t_eq "$__decision" "allow" "contract: read-only git in clean jj repo -> allow"
    run_cmd "git add ."
    t_eq "$__decision" "deny"   "contract: staged git op -> deny"
    t_ne "$__reason" ""         "contract: a deny carries a non-empty reason"
    t_ok "\"$REAL_JQ\" -e '.permissionDecision and .permissionDecisionReason' '$SANDBOX/out'" \
        "contract: deny output is JSON with decision+reason"
}

test_allow_shape() {
    clean_repo
    run_cmd "jj log"
    t_eq "$__decision" "allow" "contract: allow decision produced"
    t_contains '{"permissionDecision":"allow"' "$(cat "$SANDBOX/out")" \
        "contract: allow serialized on stdout"
}

# ===========================================================================
# tool scope: only `bash` intercepted
# ===========================================================================
test_nonbash_tools_allowed() {
    clean_repo
    for tool in Read Write Edit MultiEdit Bash PowerShell; do
        mkpayload_obj "$SANDBOX/p.json" "$REPO" "$tool" "git push origin main"
        run_hook "$SANDBOX/p.json" tools
        t_eq "$__decision" "allow" "scope: non-bash tool '$tool' passes through"
    done
}

# ===========================================================================
# malformed input
# ===========================================================================
test_malformed() {
    clean_repo
    : > "$SANDBOX/empty.json"
    run_hook "$SANDBOX/empty.json" tools
    t_eq "$__decision" "deny" "malformed: empty stdin denied"
    t_eq "$__reason"  "jj-preflight: could not parse tool payload" "malformed: empty -> R_MALFORMED"

    printf '%s' 'not json at all' > "$SANDBOX/bad.json"
    run_hook "$SANDBOX/bad.json" tools
    t_eq "$__decision" "deny" "malformed: invalid JSON denied"

    "$REAL_JQ" -n --arg c "$REPO" '{cwd:$c, toolArgs:{command:"ls"}}' > "$SANDBOX/qt.json"
    run_hook "$SANDBOX/qt.json" tools
    t_eq "$__decision" "deny" "malformed: missing toolName denied"

    "$REAL_JQ" -n --arg t bash '{toolName:$t, toolArgs:{command:"ls"}}' > "$SANDBOX/qc.json"
    run_hook "$SANDBOX/qc.json" tools
    t_eq "$__decision" "deny" "malformed: missing cwd denied"

    mkpayload_obj "$SANDBOX/p.json" "$REPO" bash ""
    run_hook "$SANDBOX/p.json" tools
    t_eq "$__decision" "deny" "malformed: empty command denied"
    t_eq "$__reason" "jj-preflight: could not parse tool payload" "malformed: empty command -> R_MALFORMED"
}

# ===========================================================================
# non-jj / non-repo
# ===========================================================================
test_non_repo() {
    mksandbox
    NR="$SANDBOX/nr"; mkdir -p "$NR"
    unset JJ_STUB_ROOT JJ_STUB_BOOKMARK JJ_STUB_CONFLICTS
    mkpayload_obj "$SANDBOX/p.json" "$NR" bash "ls"
    run_hook "$SANDBOX/p.json" tools
    t_eq "$__decision" "allow" "non-repo: pure read-only command allowed"
    for c in "git status" "git log" "git push" "jj log" "jj status"; do
        mkpayload_obj "$SANDBOX/p.json" "$NR" bash "$c"
        run_hook "$SANDBOX/p.json" tools
        t_eq "$__decision" "deny" "non-repo: '$c' denied"
        t_eq "$__reason" "jj-preflight: no jj or git repository found for command target" \
            "non-repo: '$c' -> R_NON_REPO"
    done
}

# ===========================================================================
# clean jj: read-only git allowed; git mutations denied; jj ops allowed
# ===========================================================================
test_clean_jj() {
    clean_repo
    for c in "git status" "git log" "git diff" "git diff --cached" "git branch" "git tag"; do
        run_cmd "$c"
        t_eq "$__decision" "allow" "clean: read-only '$c' allowed"
    done
    for c in "git add ." "git add -A" "git commit -m x" "git reset --hard" \
             "git push origin main" "git checkout main" "git switch feat"; do
        run_cmd "$c"
        t_eq "$__decision" "deny" "clean: mutating '$c' denied"
        t_eq "$__reason" "jj-preflight: git mutating/staging operation in a jj-managed repo" \
            "clean: '$c' -> R_GIT_MUTATE"
    done
    for c in "jj status" "jj log" "jj diff" "jj describe -m msg" "jj new" \
             "jj bookmark set main" "jj rebase -b @"; do
        run_cmd "$c"
        t_eq "$__decision" "allow" "clean: jj op '$c' allowed"
    done
}

# ===========================================================================
# tracked / staged / untracked .jj  + explicit / broad git adds
# ===========================================================================
test_jj_adds() {
    clean_repo
    run_cmd "git add .jj/repo/store/data"
    t_eq "$__reason" "jj-preflight: git mutating/staging operation in a jj-managed repo" \
        "adds: explicit .jj add -> R_GIT_MUTATE"
    for c in "git add ." "git add -A" "git add --all" "git add -u" "git add .jj"; do
        run_cmd "$c"
        t_eq "$__decision" "deny" "adds: broad '$c' denied"
    done
    run_cmd "git rm .jj/repo/store/old"
    t_eq "$__decision" "deny" "adds: git rm (tracked .jj) denied"
}

# ===========================================================================
# copy / rename / archive / extraction
# ===========================================================================
test_copy_rename_archive() {
    clean_repo
    run_cmd "git mv a b"
    t_eq "$__reason" "jj-preflight: git mutating/staging operation in a jj-managed repo" \
        "copy: git mv -> R_GIT_MUTATE"
    for c in "cp -r . newdir" "mv src dst" "tar -xf archive.tar.gz" "unzip files.zip" \
             "curl -O https://example.com/x"; do
        run_cmd "$c"
        t_eq "$__reason" "jj-preflight: command is not a recognized read-only operation" \
            "copy: '$c' -> R_UNSAFE_CMD"
    done
}

# ===========================================================================
# compound / wrappers / command substitution / write redirection
# ===========================================================================
test_compound_and_wrappers() {
    clean_repo
    for c in "git status && rm -rf /" "git log || true" "echo hi; ls" \
             "echo \$(git status)" "echo \`git status\`" \
             "sudo git pull" "eval rm -rf ." "xargs rm" "env git push" \
             "nohup git pull" "setsid git reset"; do
        run_cmd "$c"
        t_eq "$__reason" "jj-preflight: compound or wrapped command with unsafe component" \
            "compound: '$c' -> R_COMPOUND"
        t_eq "$__decision" "deny" "compound: '$c' denied"
    done
    run_cmd "echo hi > file.txt"
    t_eq "$__reason" "jj-preflight: compound or wrapped command with unsafe component" \
        "redirection: write '>' -> R_COMPOUND"
    run_cmd "cat <>file.txt"
    t_eq "$__reason" "jj-preflight: compound or wrapped command with unsafe component" \
        "redirection: read/write '<>' -> R_COMPOUND"
}

# pipeline handling (real behavior): the hook inspects the first verb of a
# `|` pipeline; a safe first verb is allowed, an unsafe first verb is denied.
test_pipelines() {
    clean_repo
    run_cmd "cat a | grep b"
    t_eq "$__decision" "allow" "pipeline: read-only pipeline allowed"
    run_cmd "cat x | grep y | tail -n 1"
    t_eq "$__decision" "allow" "pipeline: read-only multi-pipeline allowed"
    run_cmd "rm x | cat"
    t_eq "$__decision" "deny" "pipeline: unsafe first verb denied"
}

# ===========================================================================
# unresolved conflicts
# ===========================================================================
test_conflicts() {
    clean_repo
    export JJ_STUB_CONFLICTS=1
    for c in "git status" "git add ." "jj describe -m x" "jj rebase -b @"; do
        run_cmd "$c"
        t_eq "$__reason" "jj-preflight: repository has unresolved conflicts" \
            "conflicts: '$c' -> R_CONFLICT"
    done
    run_cmd "jj status"
    t_eq "$__decision" "allow" "conflicts: read-only jj status still allowed"
    unset JJ_STUB_CONFLICTS
}

# ===========================================================================
# bookmark present vs ambiguous/unverifiable target
# ===========================================================================
test_bookmark_and_ambiguous() {
    clean_repo
    JJ_STUB_ROOT="/somewhere/else"; export JJ_STUB_ROOT
    run_cmd "git log"
    t_eq "$__reason" "jj-preflight: could not verify jj metadata/repository state" \
        "ambig: unverifiable root, git read-only -> R_METADATA"
    run_cmd "git add ."
    t_eq "$__reason" "jj-preflight: could not verify jj metadata/repository state" \
        "ambig: unverifiable root, git mutate -> R_METADATA"
    run_cmd "jj log"
    t_eq "$__decision" "allow" "ambig: unverifiable root, jj read-only allowed"
    JJ_STUB_ROOT="$REPO"; export JJ_STUB_ROOT
}

# ===========================================================================
# mid-operation (git operation markers)
# ===========================================================================
test_mid_operation() {
    clean_repo
    for m in MERGE_HEAD REBASE_HEAD CHERRY_PICK_HEAD index.lock; do
        gitop_mark "$REPO" "$m"
        run_cmd "git status"
        t_eq "$__reason" "jj-preflight: a git operation is in progress" \
            "midop: '$m' + git status -> R_GIT_OP"
        run_cmd "git add ."
        t_eq "$__reason" "jj-preflight: a git operation is in progress" \
            "midop: '$m' + git add -> R_GIT_OP"
        rm -f "$REPO/.git/$m"
    done
    run_cmd "jj log"
    t_eq "$__decision" "allow" "midop: jj read-only allowed during git op"
}

# ===========================================================================
# detached working-copy commit
# ===========================================================================
test_detached() {
    clean_repo
    unset JJ_STUB_BOOKMARK
    run_cmd "git status"
    t_eq "$__decision" "allow" "detached: read-only git status allowed"
    run_cmd "git add ."
    t_eq "$__reason" "jj-preflight: working-copy commit is detached" \
        "detached: git add -> R_DETACHED"
    run_cmd "jj describe -m x"
    t_eq "$__reason" "jj-preflight: working-copy commit is detached" \
        "detached: jj describe -> R_DETACHED"
    run_cmd "jj log"
    t_eq "$__decision" "allow" "detached: jj read-only allowed"
    export JJ_STUB_BOOKMARK=1
}

# ===========================================================================
# unavailable tools
# ===========================================================================
test_unavailable_jq() {
    clean_repo
    # Hermetic: jq must be genuinely absent from the minimal PATH (no
    # /usr/bin:/bin fallback), independent of the host's default PATH.
    t_eq "$(minjq_path)" "$(minjq_path)" "nojq: hermetic PATH built"
    t_ok "! path_has jq '$(minjq_path)'" "nojq: jq is genuinely absent from hermetic PATH"
    t_ok "path_has cat '$(minjq_path)'"  "nojq: coreutils still present for the hook"
    mkpayload_obj "$SANDBOX/p.json" "$REPO" bash "git status"
    run_hook "$SANDBOX/p.json" nojq
    t_eq "$__decision" "deny" "nojq: jq unavailable -> deny"
    t_eq "$__reason" "jj-preflight: could not parse tool payload" "nojq: -> R_MALFORMED"
}

test_unavailable_jj() {
    clean_repo
    # Hermetic: jj must be genuinely absent from the minimal PATH.
    t_ok "! path_has jj '$(minjj_path)'" "nojj: jj is genuinely absent from hermetic PATH"
    t_ok "path_has jq '$(minjj_path)'"  "nojj: jq still present for the hook"
    mkpayload_obj "$SANDBOX/p.json" "$REPO" bash "git log"
    run_hook "$SANDBOX/p.json" nojj
    t_eq "$__reason" "jj-preflight: could not verify jj metadata/repository state" \
        "nojj: git read-only in jj repo -> R_METADATA"
    mkpayload_obj "$SANDBOX/p.json" "$REPO" bash "jj status"
    run_hook "$SANDBOX/p.json" nojj
    t_eq "$__decision" "allow" "nojj: jj read-only allowed (cannot verify, non-mutating)"
}

# ===========================================================================
# toolArgs input forms
# ===========================================================================
test_input_forms() {
    clean_repo
    mkpayload_str "$SANDBOX/p.json" "$REPO" bash '{"command":"git status"}'
    run_hook "$SANDBOX/p.json" tools
    t_eq "$__decision" "allow" "form: serialized-string toolArgs read correctly"

    mkpayload_arr "$SANDBOX/p.json" "$REPO" bash '["git","log"]'
    run_hook "$SANDBOX/p.json" tools
    t_eq "$__decision" "allow" "form: array toolArgs read correctly"

    mkpayload_arr "$SANDBOX/p.json" "$REPO" bash '["-c","git add ."]'
    run_hook "$SANDBOX/p.json" tools
    t_eq "$__decision" "deny" "form: '-c git add' array denied"
}

# ===========================================================================
# malformed/redaction: fixed vocabulary, no secrets/user data leaked
# ===========================================================================
test_redaction() {
    clean_repo
    run_cmd "git push https://user:Sup3rSecretTok3n@example.com/repo"
    t_eq "$__decision" "deny" "redaction: sensitive command still denied"
    t_not_contains "Sup3rSecretTok3n" "$__reason" "redaction: secret never in reason"
    t_not_contains "Sup3rSecretTok3n" "$(cat "$SANDBOX/out")" "redaction: secret never on stdout"
    t_not_contains "git push" "$__reason" "redaction: command text never echoed in reason"

    run_cmd "git commit -m 'contains AWS_SECRET_ACCESS_KEY=abc'"
    t_not_contains "abc" "$__reason" "redaction: inline secret not echoed"
    # reason must come from the fixed vocabulary
    vocab_ok=0
    for r in \
        "could not parse tool payload" \
        "no jj or git repository found for command target" \
        "git mutating/staging operation in a jj-managed repo" \
        "command is not a recognized read-only operation" \
        "compound or wrapped command with unsafe component" \
        "repository has unresolved conflicts" \
        "a git operation is in progress" \
        "working-copy commit is detached" \
        "could not verify jj metadata/repository state"; do
        [ "$__reason" = "jj-preflight: $r" ] && vocab_ok=1
    done
    t_eq "$vocab_ok" "1" "redaction: deny reason is from the fixed vocabulary"
}

# ===========================================================================
# no mutation
# ===========================================================================
test_no_mutation() {
    clean_repo
    snapshot() {
        ( cd "$REPO" && find . -type f | sort ) | cksum
        ( cd "$REPO" && find . -type f -exec cksum {} \; ) | cksum
    }
    before="$(snapshot)"
    run_cmd "git add ."
    run_cmd "git push -f origin gh-pages"
    after="$(snapshot)"
    t_eq "$after" "$before" "no-mutate: hook leaves repo contents byte-identical"
}

# ===========================================================================
# command / builtin / type wrappers. Under the intended final contract these
# indirection verbs (`command X` / `builtin X` re-exec, and `type <name>`) are
# NOT treated as safe read-only verbs — they can re-exec / obscure what is
# actually run — so any `command`/`builtin`/`type`-headed invocation is denied
# as a wrapped command (R_COMPOUND), as are the recognised wrapper verbs
# (env/sudo/eval/xargs...).
# ===========================================================================
test_wrappers_command_builtin() {
    clean_repo
    # `command` / `builtin` / `type` nested execution -> deny (wrapped).
    for c in "command git status" "command git push -f" "command jj log" \
             "builtin echo hi" "builtin :" "type git" "type jj"; do
        run_cmd "$c"
        t_eq "$__decision" "deny" "wrapper: '$c' -> deny (indirection, final contract)"
        t_eq "$__reason" "jj-preflight: compound or wrapped command with unsafe component" \
            "wrapper: '$c' -> R_COMPOUND (final contract)"
    done
    # The recognised wrapper verbs are already denied as compound.
    for c in "env git status" "env git push" "sudo git log"; do
        run_cmd "$c"
        t_eq "$__reason" "jj-preflight: compound or wrapped command with unsafe component" \
            "wrapper: '$c' -> R_COMPOUND"
    done
}

# ===========================================================================
# process substitution: `<( ... )` / `>( ... )` spawns a subcommand whose body
# is NOT visible to the verb scan, so it can smuggle unsafe/ mutating
# execution. Under the intended final contract it is denied as a compound /
# wrapped form (R_COMPOUND), mirroring command substitution.
# ===========================================================================
test_process_substitution() {
    clean_repo
    for c in "cat <(git status)" "cat <(rm -rf /)" "diff <(git log) <(git status)" \
             "grep x <(cat file)" "tee >(grep x)"; do
        run_cmd "$c"
        t_eq "$__decision" "deny" "procsub: '$c' -> deny (final contract)"
        t_eq "$__reason" "jj-preflight: compound or wrapped command with unsafe component" \
            "procsub: '$c' -> R_COMPOUND (final contract)"
    done
}

# ===========================================================================
# newline separators: a newline is a command separator, exactly like `;` and
# `&&`. Under the intended final contract ANY newline-separated command is
# denied as a compound form (R_COMPOUND), so a read-only multi-line command is
# no longer allowed.
# ===========================================================================
test_newline_separators() {
    clean_repo
    run_cmd "rm -rf /
cat x"
    t_eq "$__decision" "deny" "newline: unsafe first line denied"
    t_eq "$__reason" "jj-preflight: compound or wrapped command with unsafe component" \
        "newline: unsafe first line -> R_COMPOUND (final contract)"
    run_cmd "cat x
rm -rf /"
    t_eq "$__decision" "deny" "newline: unsafe later line denied"
    t_eq "$__reason" "jj-preflight: compound or wrapped command with unsafe component" \
        "newline: unsafe later line -> R_COMPOUND (final contract)"
    run_cmd "git push
ls"
    t_eq "$__decision" "deny" "newline: git mutation line denied"
    t_eq "$__reason" "jj-preflight: compound or wrapped command with unsafe component" \
        "newline: git mutation line -> R_COMPOUND (final contract)"
    run_cmd "git status
git log"
    t_eq "$__decision" "deny" "newline: read-only multi-line now denied (separator)"
    t_eq "$__reason" "jj-preflight: compound or wrapped command with unsafe component" \
        "newline: read-only multi-line -> R_COMPOUND (final contract)"
}

# ===========================================================================
# unsafe git branch/tag/config/remote mutations. Under the intended final
# contract these are DENIED as git mutations (R_GIT_MUTATE) even in a clean
# repo — subcommand-level read-only classification is NOT a license to mutate.
# The conflict / git-op state checks below also deny them.
# ===========================================================================
test_unsafe_git_subcommand_mutations() {
    clean_repo
    for c in "git branch -d foo" "git branch -D foo" "git branch -m old new" \
             "git branch --set-upstream-to=origin/main" \
             "git tag -d v1" "git tag -f v1 HEAD" "git tag --delete v1" \
             "git config user.email a@b.c" "git config --unset user.email" \
             "git config --global init.defaultBranch main" "git config --remove-section user" \
             "git remote add origin https://x/y" "git remote set-url origin https://z" \
             "git remote remove origin" "git remote prune origin" "git remote rename a b"; do
        run_cmd "$c"
        t_eq "$__decision" "deny" "git-mut/clean: '$c' -> deny (final contract)"
        t_eq "$__reason" "jj-preflight: git mutating/staging operation in a jj-managed repo" \
            "git-mut/clean: '$c' -> R_GIT_MUTATE (final contract)"
    done
    # Conflicts: the state check wins over the read-only classification.
    export JJ_STUB_CONFLICTS=1
    for c in "git branch -d foo" "git tag -d v1" "git config user.email a@b.c" \
             "git remote add origin https://x/y"; do
        run_cmd "$c"
        t_eq "$__reason" "jj-preflight: repository has unresolved conflicts" \
            "git-mut/conflict: '$c' -> R_CONFLICT"
    done
    unset JJ_STUB_CONFLICTS
    # Git operation in progress: denied for these too.
    gitop_mark "$REPO" MERGE_HEAD
    for c in "git branch -d foo" "git remote add origin https://x/y"; do
        run_cmd "$c"
        t_eq "$__reason" "jj-preflight: a git operation is in progress" \
            "git-mut/gitop: '$c' -> R_GIT_OP"
    done
    rm -f "$REPO/.git/MERGE_HEAD"
}

# ===========================================================================
# jj post-mutation / recovery + remote ops. Under the intended final contract the
# jj "read-only classified" families (op / file / util / debug) and every
# git-remote-touching jj operation (remote add / fetch / import / export /
# clone / init / push) are DENIED as mutations (R_GIT_MUTATE). Local jj editing
# (new / describe / bookmark set / rebase) remains allowed in a clean repo — jj
# is still the preferred VCS; it is the remote/git and admin-state operations
# that are locked down.
# ===========================================================================
test_jj_post_mutation_ops() {
    clean_repo
    # jj op/file/util/debug misuse (op undo/restore, file untrack, util, debug)
    # is denied outright -> R_GIT_MUTATE (mutating jj state / git layer).
    for c in "jj op undo" "jj op restore 0123abc" "jj file untrack src/a.rs" \
             "jj util" "jj debug"; do
        run_cmd "$c"
        t_eq "$__decision" "deny" "jj-ops: '$c' -> deny (final contract)"
        t_eq "$__reason" "jj-preflight: git mutating/staging operation in a jj-managed repo" \
            "jj-ops: '$c' -> R_GIT_MUTATE (final contract)"
    done
    # jj git remote/clone/init and every jj git push/import/export/fetch reach
    # the git/remote layer -> R_GIT_MUTATE.
    for c in "jj git remote add origin https://x/y" "jj git clone https://x/y" \
             "jj git init" "jj git push" "jj git fetch" "jj git import"; do
        run_cmd "$c"
        t_eq "$__decision" "deny" "jj-ops: '$c' -> deny (final contract)"
        t_eq "$__reason" "jj-preflight: git mutating/staging operation in a jj-managed repo" \
            "jj-ops: '$c' -> R_GIT_MUTATE (final contract)"
    done
    # Even during an unresolved conflict these banned mutating jj ops are denied;
    # the conflict state supplies the reason (R_CONFLICT) — a deny regardless.
    export JJ_STUB_CONFLICTS=1
    run_cmd "jj op undo"
    t_eq "$__decision" "deny" "jj-ops: 'jj op undo' denied despite conflicts"
    t_eq "$__reason" "jj-preflight: repository has unresolved conflicts" \
        "jj-ops: 'jj op undo' in conflict -> R_CONFLICT"
    unset JJ_STUB_CONFLICTS
}

# ===========================================================================
# force push: every direct git force-push form is denied; every `jj git push`
# form (force or ambiguous/unspecified target) is also DENIED under the
# intended final contract — pushing a jj-managed repo's bookmarks to a remote
# git is the risky operation and is locked down (R_GIT_MUTATE).
# ===========================================================================
test_force_push() {
    clean_repo
    for c in "git push --force origin main" "git push -f origin gh-pages" \
             "git push --force-with-lease origin main" "git push --force-with-lease"; do
        run_cmd "$c"
        t_eq "$__reason" "jj-preflight: git mutating/staging operation in a jj-managed repo" \
            "force: '$c' -> R_GIT_MUTATE"
    done
    # All jj git push forms: force AND ambiguous / unspecified targets.
    for c in "jj git push --force" "jj git push -f" "jj git push --force-with-lease" \
             "jj git push --allow-new-parents --force" \
             "jj git push origin main --force" "jj git push origin" \
             "jj git push" "jj git push --remote origin"; do
        run_cmd "$c"
        t_eq "$__decision" "deny" "force: '$c' -> deny (final contract)"
        t_eq "$__reason" "jj-preflight: git mutating/staging operation in a jj-managed repo" \
            "force: '$c' -> R_GIT_MUTATE (final contract)"
    done
}

# ===========================================================================
# staged/tracked .jj and index checks: any git staging/mutation that touches
# the index or .jj tree is denied in a jj-managed repo.
# ===========================================================================
test_staged_index_jj() {
    clean_repo
    for c in "git add .jj" "git add .jj/repo/store/data" "git add -A" "git add -u" \
             "git add -i" "git add ." "git stage ." \
             "git rm .jj/repo/store/old" "git rm -r .jj" "git rm --cached .jj/repo/store/data" \
             "git update-index --add .jj/repo/store/data" \
             "git update-index --assume-unchanged .jj/repo/store/data" \
             "git reset .jj" "git restore --staged .jj/repo/store/data" \
             "git read-tree HEAD" "git write-tree" "git checkout-index -a" \
             "git commit -m x" "git reset --hard"; do
        run_cmd "$c"
        t_eq "$__reason" "jj-preflight: git mutating/staging operation in a jj-managed repo" \
            "index/.jj: '$c' -> R_GIT_MUTATE"
    done
}

# ===========================================================================
# jj exit-status simulation: a failing `jj root` makes metadata unverifiable
# (R_METADATA for git ops); a failing conflict query still yields empty
# conflicts (root failure is what trips the metadata path).
# ===========================================================================
test_jj_exit_status() {
    clean_repo
    JJ_STUB_ROOT_FAIL=1; export JJ_STUB_ROOT_FAIL
    run_cmd "git status"
    t_eq "$__reason" "jj-preflight: could not verify jj metadata/repository state" \
        "exit-status: failing jj root + git read-only -> R_METADATA"
    run_cmd "jj log"
    t_eq "$__decision" "allow" "exit-status: failing jj root, jj read-only allowed"
    unset JJ_STUB_ROOT_FAIL

    # A non-zero conflict-log query (jj error) yields "no conflicts"; combined
    # with a succeeded root, read-only git stays allowed.
    JJ_STUB_LOG_FAIL=1; export JJ_STUB_LOG_FAIL
    run_cmd "git status"
    t_eq "$__decision" "allow" "exit-status: failing conflict query, clean root -> allow"
    unset JJ_STUB_LOG_FAIL
}

# ===========================================================================
# conflict stub modeling: the hook must invoke the conflict query with the
# VALID real-jj arg shape `-T description` (a real template keyword — `-T x` is
# not), and the stub must model failure statuses. These assertions lock that in.
# ===========================================================================
test_conflict_stub_modeling() {
    clean_repo
    # (a) The recorded `-T` template must be exactly `description`, proving the
    # hook passes a real template keyword via the real-jj arg shape.
    export JJ_STUB_CONFLICTS=1
    export JJ_STUB_RECORD_TPL="$SANDBOX/tpl.txt"
    run_cmd "jj describe -m x"
    rec="$(cat "$JJ_STUB_RECORD_TPL" 2>/dev/null || true)"
    t_eq "$rec" "tpl=description" \
        "conflict-stub: hook invokes conflict query with '-T description' (got '$rec')"
    unset JJ_STUB_RECORD_TPL
    # Drop the conflict state before the failure-status checks below.
    unset JJ_STUB_CONFLICTS
    # (b) Failure statuses: a failing conflict query under a clean root yields no
    # conflicts so read-only git stays allowed; a failing bookmark query detaches
    # the working copy (read-only git allowed, mutation denied).
    JJ_STUB_LOG_FAIL=1; export JJ_STUB_LOG_FAIL
    run_cmd "git status"
    t_eq "$__decision" "allow" "conflict-stub: log-fail + clean root -> allow"
    unset JJ_STUB_LOG_FAIL
    JJ_STUB_BOOKMARK_FAIL=1; export JJ_STUB_BOOKMARK_FAIL
    run_cmd "git add ."
    t_eq "$__reason" "jj-preflight: working-copy commit is detached" \
        "conflict-stub: bookmark-fail -> treated detached, git add denied"
    unset JJ_STUB_BOOKMARK_FAIL
    unset JJ_STUB_CONFLICTS
}

# ===========================================================================
# EMPTY-DESCRIPTION CONFLICT. A conflicted revision whose jj DESCRIPTION is
# empty still produces output from the hook's `jj log -T description` conflict
# query — a bare newline per conflicted rev. Plain `[ -n "$out" ]` on the
# command-substituted result would strip that trailing newline and wrongly read
# "no conflict" (allowing even read-only git). The hook must detect the conflict
# from the raw output size; both a read-only `git status` and a mutating
# `git add .` must be denied R_CONFLICT in such a repo.
# ===========================================================================
test_empty_desc_conflict() {
    clean_repo
    JJ_STUB_CONFLICTS=1
    JJ_STUB_CONFLICTS_EMPTY=1
    export JJ_STUB_CONFLICTS JJ_STUB_CONFLICTS_EMPTY
    run_cmd "git status"
    t_eq "$__decision" "deny" \
        "emptydesc: git status denied (newline-only conflict)"
    t_eq "$__reason" "jj-preflight: repository has unresolved conflicts" \
        "emptydesc: git status -> R_CONFLICT (empty description)"
    run_cmd "git add ."
    t_eq "$__decision" "deny" \
        "emptydesc: git add denied (newline-only conflict)"
    t_eq "$__reason" "jj-preflight: repository has unresolved conflicts" \
        "emptydesc: git add -> R_CONFLICT (empty description)"
    unset JJ_STUB_CONFLICTS JJ_STUB_CONFLICTS_EMPTY
}

# ===========================================================================
# every-git/jj-OCCURRENCE + PIPELINE BYPASSES. A `|` pipeline that hides a
# mutating git/jj step behind a read-only first segment must never slip through.
# Two guards close this: the multi-invocation guard denies any command carrying
# ≥2 independent git/jj commands (one per `|` segment) as R_COMPOUND, and a
# single occurrence whose write is hidden behind a leading non-git verb or a jj
# global option (`cat f | git add -`, `jj -R path git push`) still classifies as
# the mutating op it is → R_GIT_MUTATE. Read-only single-occurrence pipelines
# remain allowed.
# ===========================================================================
test_every_git_jj_occurrence() {
    clean_repo
    # Multi-invocation pipelines (≥2 independent git/jj commands, one per `|`
    # segment) are unclassifiable per-segment and are denied outright as
    # compound (R_COMPOUND) — the every-occurrence guard. This is what stops a
    # read-only first segment from masking a mutating second one.
    for c in \
        "git status | git checkout main" \
        "git diff | git apply --index" \
        "git log | git branch -D x" \
        "jj log | jj git push --force"; do
        run_cmd "$c"
        t_eq "$__decision" "deny" \
            "every-occ: '$c' -> deny (multi-invocation pipeline)"
        t_eq "$__reason" "jj-preflight: compound or wrapped command with unsafe component" \
            "every-occ: '$c' -> R_COMPOUND (final contract)"
    done
    # A SINGLE git/jj occurrence whose write is hidden behind a leading non-git
    # verb (`cat f | git add -`) or a jj global option (`jj -R path git push`)
    # is still classified as the mutating op it is -> R_GIT_MUTATE.
    for c in "cat f | git add -" "jj -R path git push"; do
        run_cmd "$c"
        t_eq "$__decision" "deny" \
            "every-occ: '$c' -> deny (single-occurrence mutation)"
        t_eq "$__reason" "jj-preflight: git mutating/staging operation in a jj-managed repo" \
            "every-occ: '$c' -> R_GIT_MUTATE (final contract)"
    done
    # Positive control: a genuinely read-only pipeline with a single git/jj
    # occurrence stays allowed — the net must not over-deny pure reads.
    for c in "git status | wc -l" "jj log | wc -l"; do
        run_cmd "$c"
        t_eq "$__decision" "allow" \
            "every-occ: read-only pipeline '$c' still allowed"
    done
}

# ===========================================================================
# ARGUMENT-POSITION SMUGGLING. A mutating git/jj verb hidden in a LATER pipeline
# segment is preceded by a read-only first segment whose ARGUMENTS mention a
# git/jj keyword (`echo git status | git push`, `ls git log | git reset --hard`,
# `echo jj log | jj op undo`, ...). Those argument-position keywords must never
# be mistaken for the invocation — every such command is DENIED, while genuinely
# read-only single-invocation pipelines (an existing negative control) stay
# allowed.
# ===========================================================================
test_arg_position_smuggling() {
    clean_repo
    for c in \
        "echo git status | git push" \
        "ls git log | git reset --hard" \
        "printf git diff | git clean -fdx" \
        "echo git status | git push origin main --force" \
        "echo jj log | jj op undo" \
        "echo jj log | jj abandon @" \
        "echo jj file show | jj file untrack x"; do
        run_cmd "$c"
        t_eq "$__decision" "deny" \
            "argsmug: '$c' denied (argument-position smuggling)"
    done
    # Read-only pipeline negative control: a single command-position git/jj with
    # a read-only second segment stays allowed.
    for c in "git status | wc -l" "jj log | wc -l"; do
        run_cmd "$c"
        t_eq "$__decision" "allow" \
            "argsmug: read-only pipeline '$c' still allowed"
    done
}

# ===========================================================================
# jj global options carrying a VALUE (`--at-op <op>`, `--config <k>=<v>`) sit
# BEFORE the subcommand. The value after such an option is NOT the subcommand —
# so a mutating `jj git push` / `jj git fetch` hidden behind a value-carrying
# global option is still classified as the mutating op it is and maps to
# R_GIT_MUTATE, exactly like the `-R <path>` global option handled above.
# The negative control shows a read-only `jj log` behind `--at-op` stays allowed.
# ===========================================================================
test_jj_global_opt_mutations() {
    clean_repo
    for c in "jj --at-op abc git push" "jj --at-op abc git push --force" \
             "jj --at-op abc git fetch" "jj --config ui.color=always git push"; do
        run_cmd "$c"
        t_eq "$__decision" "deny" \
            "jjgopt: '$c' -> deny (final contract)"
        t_eq "$__reason" "jj-preflight: git mutating/staging operation in a jj-managed repo" \
            "jjgopt: '$c' -> R_GIT_MUTATE (final contract)"
    done
    # Serialized-string and array toolArgs forms are parsed identically.
    mkpayload_str "$SANDBOX/p.json" "$REPO" bash '{"command":"jj --at-op abc git push"}'
    run_hook "$SANDBOX/p.json" tools
    t_eq "$__decision" "deny" "jjgopt: serialized-string form denied"
    t_eq "$__reason" "jj-preflight: git mutating/staging operation in a jj-managed repo" \
        "jjgopt: serialized-string form -> R_GIT_MUTATE"
    mkpayload_arr "$SANDBOX/p.json" "$REPO" bash '["jj","--at-op","abc","git","push"]'
    run_hook "$SANDBOX/p.json" tools
    t_eq "$__decision" "deny" "jjgopt: array form denied"
    t_eq "$__reason" "jj-preflight: git mutating/staging operation in a jj-managed repo" \
        "jjgopt: array form -> R_GIT_MUTATE"
    # Negative control: a genuinely read-only jj op behind a value-carrying
    # global option stays allowed.
    run_cmd "jj --at-op abc log"
    t_eq "$__decision" "allow" "jjgopt: read-only 'jj --at-op abc log' allowed"
}

# ===========================================================================
# R_JJ_TRACKED vocabulary + REAL indexed-.jj fixture. When jj internal state
# (.jj/...) is genuinely TRACKED or stageable in the git index, mutating/
# staging git ops AND jj writes are denied with the dedicated R_JJ_TRACKED
# reason — while read-only git/jj stays allowed. Uses the real-git fixture
# lib/fixtures/indexed-jj-repo.sh so the hook's `git ls-files -- .jj` and
# `git check-ignore` inspections genuinely fire.
# ===========================================================================
test_indexed_jj_tracked() {
    mksandbox
    REPO="$SANDBOX/irepo"
    if [ ! -f "$LIB_DIR/fixtures/indexed-jj-repo.sh" ]; then
        t_fail "indexed .jj fixture is missing from the package"
        return 0
    fi
    if ! command -v git >/dev/null 2>&1; then
        t_skip "indexed .jj fixture requires git, which is unavailable"
        return 0
    fi
    if ! sh "$LIB_DIR/fixtures/indexed-jj-repo.sh" "$REPO"; then
        t_fail "indexed .jj fixture failed to build"
        return 0
    fi
    JJ_STUB_ROOT="$REPO"
    JJ_STUB_BOOKMARK=1
    unset JJ_STUB_CONFLICTS
    export JJ_STUB_ROOT JJ_STUB_BOOKMARK

    # Sanity: the fixture really has a .jj path in the git index.
    tracked="$(cd "$REPO" && git ls-files -- .jj 2>/dev/null | head -n 1)"
    t_ne "$tracked" "" "indexed: fixture has a tracked .jj path in the index"

    # Mutating/staging git ops on a repo whose .jj tree is tracked -> R_JJ_TRACKED.
    for c in "git commit -m x" "git add ." "git add -A"; do
        run_cmd "$c"
        t_eq "$__decision" "deny" "indexed: mutating '$c' denied"
        t_eq "$__reason" "jj-preflight: jj internal state is tracked or stageable by git" \
            "indexed: '$c' -> R_JJ_TRACKED"
    done
    # Read-only git stays allowed even while .jj is tracked.
    run_cmd "git status"
    t_eq "$__decision" "allow" "indexed: read-only git status still allowed"
    # A jj write while jj internals sit in the git index -> R_JJ_TRACKED.
    run_cmd "jj describe -m msg"
    t_eq "$__decision" "deny" "indexed: jj write denied"
    t_eq "$__reason" "jj-preflight: jj internal state is tracked or stageable by git" \
        "indexed: jj write -> R_JJ_TRACKED"
    # Read-only jj stays allowed.
    run_cmd "jj log"
    t_eq "$__decision" "allow" "indexed: read-only jj log still allowed"

    # Pin the R_JJ_TRACKED vocabulary entry in the packaged hook so a drift or
    # rename of the reason string is caught by the suite.
    t_contains 'R_JJ_TRACKED="jj-preflight: jj internal state is tracked or stageable by git"' \
        "$(grep -n '^R_JJ_TRACKED=' "$HOOK" 2>/dev/null || true)" \
        "indexed: R_JJ_TRACKED vocabulary present in packaged hook"
}

# ===========================================================================
test_contract_shape
test_allow_shape
test_nonbash_tools_allowed
test_malformed
test_non_repo
test_clean_jj
test_jj_adds
test_copy_rename_archive
test_compound_and_wrappers
test_pipelines
test_conflicts
test_bookmark_and_ambiguous
test_mid_operation
test_detached
test_unavailable_jq
test_unavailable_jj
test_input_forms
test_redaction
test_no_mutation
test_wrappers_command_builtin
test_process_substitution
test_newline_separators
test_unsafe_git_subcommand_mutations
test_jj_post_mutation_ops
test_force_push
test_staged_index_jj
test_jj_exit_status
test_conflict_stub_modeling
test_empty_desc_conflict
test_every_git_jj_occurrence
test_arg_position_smuggling
test_jj_global_opt_mutations
test_indexed_jj_tracked

cleanup_sandbox
t_done
