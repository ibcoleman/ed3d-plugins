#!/usr/bin/env python3
"""Shared, offline, stdlib-only parser for portability-audit evidence.

Single source of truth for the portability-audit evidence schema and for
parsing retrieved content into normalized dependency records.  Imported by
``validate_portability_audit.py`` and ``replay_portability_evidence.py`` so
the schema, the token scanner, normalization, and the closure helpers live
in exactly one place and produce byte-identical results in both tools.

What this parser scans
----------------------
The parser scans the ``content`` field of every evidence ``resources`` record
for polytoken dependency references of two kinds:

* ``transclude`` calls whose quoted target is a ``polytoken://`` URI::

      {{ transclude("polytoken://system_prompts/facet.md") }}

  A single call uses single quotes; a double call uses double quotes.  The
  recorded dependency carries ``source = "transclude"``.  A transclude whose
  quoted target is a local file path (not a polytoken URI) is not a polytoken
  dependency and is ignored by this scanner (local paths are captured
  separately as ``local_citations``).

* literal ``polytoken://`` tokens.  A token runs from ``polytoken://`` up to
  the first terminator character.  The terminator set is whitespace and
  ``()[]{}'\",&;``.  Any ``polytoken://`` token with a path is a dependency
  (the authority -- ``facets``, ``subagents``, ``system_prompts``, ``vfs``,
  ... -- is not restricted).

Unsupported URI schemes (anything other than ``polytoken``, ``http``, or
``https``) are warned on stderr only and do **not** become dependencies;
``http(s)`` URLs are validated for syntax offline by the replay/validator and
never become dependencies.

Dependencies are normalized and sorted lexically by target (tie-broken by
line, then source) so every function returns a deterministic order.
Warnings are emitted in scan order (line order per content, contents
processed in sorted URI order by the callers), so two processes scanning the
same evidence produce byte-identical stderr.

The evidence schema is a fixed eight-array record (unknown keys are
rejected by the validator)::

    roots                    list  exactly the six root facet/subagent URIs
    resources                list  retrieved-resource records
    unresolved_references    list  referenced polytoken URIs not retrieved
    semantic_sources         list  semantic-id -> capability -> evidence uri
    local_citations          list  local file paths cited by the audit
    workflow_stages          list  workflow-stage records
    case_study_citations     list  case-study citation records
    manual_review            list  manual-review records (id, status, note)

A ``resources`` record has the required fields::

    uri, parent_uri, retrieval_status, content, content_sha256,
    discovered_references

Root resources have ``parent_uri = null``; every non-root resource has a
string ``parent_uri``.  ``content`` holds the full ``polytoken vfs cat``
output and ``content_sha256`` its raw SHA-256.

Runnable directly (used by the hermetic subprocess parser tests):

    python3 portability_evidence_parser.py --scan CONTENT.txt
"""
import hashlib
import json
import re
import sys

# ---------------------------------------------------------------------------
# Schema constants
# ---------------------------------------------------------------------------

SCHEMA_ID = "portability-evidence/v1"

# The eight top-level evidence arrays (exactly these; unknown keys rejected).
EVIDENCE_KEYS = (
    "roots",
    "resources",
    "unresolved_references",
    "semantic_sources",
    "local_citations",
    "workflow_stages",
    "case_study_citations",
    "manual_review",
)

# The six exact root facet/subagent URIs (canonical / lexical order).
EXPECTED_ROOTS = (
    "polytoken://facets/plan.md",
    "polytoken://facets/execute.md",
    "polytoken://facets/orchestrate.md",
    "polytoken://subagents/researcher.md",
    "polytoken://subagents/plan-reviewer.md",
    "polytoken://subagents/general-purpose.md",
)

# The 12 exact capability IDs.
CAPABILITY_IDS = (
    "RESEARCH_DECOMPOSITION",
    "SUBAGENT_HANDOFF",
    "EVIDENCE_CONTRACTS",
    "FACET_SEPARATION",
    "MODEL_TOOL_SKILL_SCOPING",
    "PLAN_REVIEW_GATE",
    "ADVERSARIAL_REVIEW",
    "MECHANICAL_ENFORCEMENT",
    "CONTEXT_RESUME_STATE",
    "COMPLETION_SUMMARY",
    "TEMPLATING_COMPOSABILITY",
    "OBSERVABILITY",
)

# The 23 exact semantic IDs.
SEMANTIC_IDS = (
    "SUBAGENT_INVOCATION",
    "SUBAGENT_ISOLATION",
    "SUBAGENT_RESULT_RETURN",
    "SUBAGENT_TOOL_INHERITANCE",
    "SUBAGENT_MODEL_CONFIG",
    "SUBAGENT_SKILL_ACCESS",
    "FACET_PROMPT_COMPOSITION",
    "FACET_TOOL_FILTERING",
    "FACET_SKILL_FILTERING",
    "FACET_MODEL_SELECTION",
    "FACET_TRANSITIONS",
    "FACET_COMPACTION_HINT",
    "FACET_PERMISSION_HINT",
    "SKILL_LOADING",
    "HOOK_TIMING",
    "HOOK_ENFORCEMENT",
    "TEMPLATING_RUNTIME",
    "TRANSCLUDE_SEMANTICS",
    "VFS_INSPECTION",
    "SESSION_CONTINUITY",
    "SESSION_CLEAR",
    "SESSION_COMPACTION",
    "WEB_SEARCH",
)

# The 5 exact manual-review IDs.
MANUAL_REVIEW_IDS = ("WF-1", "WF-2", "CASE-1", "SRC-1", "SRC-2")

# Approved semantic-source contract: claim identity, capability assignment,
# source metadata, and the claim supported by that source.
SEMANTIC_SOURCE_FIELDS = ("claim_id", "capability", "url",
                          "revision_or_version", "retrieval_date",
                          "supported_claim", "evidence_class")
EVIDENCE_CLASSES = ("primary", "secondary", "local", "observed", "unresolved")

# Canonical capability assignment for each of the 23 claims.
SEMANTIC_CAPABILITIES = {
    "WEB_SEARCH": "RESEARCH_DECOMPOSITION",
    "SUBAGENT_INVOCATION": "SUBAGENT_HANDOFF",
    "SUBAGENT_RESULT_RETURN": "SUBAGENT_HANDOFF",
    "SKILL_LOADING": "EVIDENCE_CONTRACTS",
    "SESSION_CONTINUITY": "EVIDENCE_CONTRACTS",
    "FACET_PROMPT_COMPOSITION": "FACET_SEPARATION",
    "FACET_TRANSITIONS": "FACET_SEPARATION",
    "FACET_MODEL_SELECTION": "FACET_SEPARATION",
    "SUBAGENT_TOOL_INHERITANCE": "MODEL_TOOL_SKILL_SCOPING",
    "SUBAGENT_SKILL_ACCESS": "MODEL_TOOL_SKILL_SCOPING",
    "FACET_TOOL_FILTERING": "MODEL_TOOL_SKILL_SCOPING",
    "FACET_SKILL_FILTERING": "MODEL_TOOL_SKILL_SCOPING",
    "SUBAGENT_MODEL_CONFIG": "PLAN_REVIEW_GATE",
    "SUBAGENT_ISOLATION": "ADVERSARIAL_REVIEW",
    "FACET_PERMISSION_HINT": "MECHANICAL_ENFORCEMENT",
    "HOOK_TIMING": "MECHANICAL_ENFORCEMENT",
    "HOOK_ENFORCEMENT": "MECHANICAL_ENFORCEMENT",
    "FACET_COMPACTION_HINT": "CONTEXT_RESUME_STATE",
    "SESSION_COMPACTION": "COMPLETION_SUMMARY",
    "SESSION_CLEAR": "COMPLETION_SUMMARY",
    "TEMPLATING_RUNTIME": "TEMPLATING_COMPOSABILITY",
    "TRANSCLUDE_SEMANTICS": "TEMPLATING_COMPOSABILITY",
    "VFS_INSPECTION": "OBSERVABILITY",
}

POLYTOKEN_SCHEME = "polytoken://"

# retrieval_status values a resources record may claim.
RETRIEVAL_STATUSES = ("retrieved", "unresolved")

# Dependency discovery source values.
DEP_SOURCES = ("transclude", "literal")

# Case-study citation status values.
CASE_STATUSES = ("observed", "unresolved")

# ---------------------------------------------------------------------------
# Tokenization
# ---------------------------------------------------------------------------

# Specified terminators for polytoken:// tokens: whitespace plus punctuation
# that ends an inline reference.
URI_TERMINATORS = " \t\r\n()[]{}'\",&;"
_TOKEN_CLASS = "[^%s]" % re.escape(URI_TERMINATORS)

TRANSCLUDE_OPEN_RE = re.compile(r"transclude\s*\(")
TRANSCLUDE_RE = re.compile(r"transclude\s*\(\s*(['\"])(.*?)\1\s*\)")
SCHEME_TOKEN_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9+.\-]*://"
                             + _TOKEN_CLASS + "+")

# Schemes the dependency scanner treats as supported.  ``polytoken://``
# becomes a dependency; ``http(s)`` is validated for syntax offline and never
# a dependency; any other scheme warns on stderr and is not a dependency.
SUPPORTED_SCHEMES = ("polytoken", "http", "https")

_LOWERCASE_AUTH_RE = re.compile(r"^(polytoken://)([^/]+)(/.*)?$")


def _default_warn(msg):
    print("warning: %s" % msg, file=sys.stderr)


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

def normalize_uri(uri):
    """Normalize a polytoken:// URI for deterministic ordering.

    Lowercases the scheme and authority, drops the URL fragment, and strips
    a trailing ``/`` from a non-root path.  Idempotent.
    """
    u = uri.strip()
    match = _LOWERCASE_AUTH_RE.match(u)
    if not match:
        return u
    scheme, authority, path = match.groups()
    scheme = scheme.lower()
    path = (path or "").split("#", 1)[0]
    if path and path != "/":
        path = path.rstrip("/")
    return "%s%s%s" % (scheme, authority.lower(), path or "/")


def _line_of(text, index):
    return text.count("\n", 0, index) + 1


def _classify_polytoken(token, line, source, warn):
    """Validate a polytoken:// token; return a dep record or None.

    Any ``polytoken://`` token with a path is a dependency, regardless of
    authority (``facets``, ``subagents``, ``system_prompts``, ``vfs``, ...).
    A token with no path is malformed: warned on stderr, no dependency.
    """
    rest = token[len(POLYTOKEN_SCHEME):]
    # Authority must be non-empty and the path must contain a non-empty
    # component; reject forms such as polytoken:///x/empty.
    if not re.match(r"^[^/]+/.+", rest):
        warn("line %d: malformed polytoken URI (missing authority/path): %s"
             % (line, token))
        return None
    return {"target": normalize_uri(token), "line": line, "source": source}


# ---------------------------------------------------------------------------
# Content scanning
# ---------------------------------------------------------------------------

def scan_content(text, warn=_default_warn):
    """Scan content for polytoken dependency records.

    Returns ``{"references": [...]}`` sorted lexically by target, then line,
    then source.  Each reference record is ``{target, line, source}`` where
    ``source`` is ``"transclude"`` or ``"literal"``.  Malformed / unsupported
    tokens are reported through ``warn`` (default: deterministic
    ``warning: ...`` on stderr) and never become dependencies.
    """
    references = []
    transclude_spans = []

    # --- transclude calls -------------------------------------------------
    for match in TRANSCLUDE_OPEN_RE.finditer(text):
        start = match.start()
        line = _line_of(text, start)
        full = TRANSCLUDE_RE.match(text, start)
        if full:
            target = full.group(2).strip()
            # Record the quoted region so the literal scanner skips it.
            transclude_spans.append((full.start(2) - 1, full.end(2)))
            if not target:
                warn("line %d: empty transclude target" % line)
                continue
            if target.startswith(POLYTOKEN_SCHEME):
                dep = _classify_polytoken(target, line, "transclude", warn)
                if dep is not None:
                    references.append(dep)
            else:
                # A non-polytoken transclude target is not a dependency.
                # An unsupported scheme target warns on stderr only.
                sm = re.match(r"^([a-zA-Z][a-zA-Z0-9+.\-]*)://", target)
                if sm and sm.group(1).lower() not in ("http", "https"):
                    warn("line %d: unsupported uri scheme in transclude: %s"
                         % (line, sm.group(1)))
            continue
        after = text[match.end():].lstrip(" \t")
        if after.startswith(("'", '"')):
            warn("line %d: unterminated transclude call" % line)
        else:
            warn("line %d: malformed transclude call (expected quoted target)"
                 % line)

    # --- literal scheme tokens --------------------------------------------
    # ``polytoken://`` tokens become dependencies; ``http(s)`` URLs are
    # validated for syntax offline and never become dependencies; any other
    # scheme warns on stderr only and is not a dependency.
    for match in SCHEME_TOKEN_RE.finditer(text):
        token_start = match.start()
        if any(lo <= token_start < hi for lo, hi in transclude_spans):
            continue  # already captured as a transclude dependency
        token = match.group(0)
        line = _line_of(text, token_start)
        scheme = token.split("://", 1)[0].lower()
        if scheme == "polytoken":
            dep = _classify_polytoken(token, line, "literal", warn)
            if dep is not None:
                references.append(dep)
        elif scheme in ("http", "https"):
            continue  # not a dependency; never warned
        else:
            warn("line %d: unsupported uri scheme: %s" % (line, scheme))

    references.sort(key=lambda r: (r["target"], r["line"], r["source"]))
    return {"references": references}


def references_from_scan(scan):
    """Return the sorted reference-record list from a scan result."""
    return sorted(scan["references"], key=lambda r: (r["target"], r["line"],
                                                     r["source"]))


# ---------------------------------------------------------------------------
# Closure helpers
# ---------------------------------------------------------------------------

def adjacency_from_resources(resources):
    """Build a polytoken-only adjacency dict from resources records.

    ``resources`` maps each retrieved URI to a set of referenced polytoken
    URIs (the ``discovered_references`` targets).  Only ``polytoken://``
    targets contribute edges.
    """
    adjacency = {}
    for record in resources:
        uri = record.get("uri")
        if not isinstance(uri, str):
            continue
        targets = set()
        for ref in record.get("discovered_references") or []:
            if isinstance(ref, dict) and \
                    str(ref.get("target", "")).startswith(POLYTOKEN_SCHEME):
                targets.add(ref["target"])
        adjacency[uri] = targets
    return adjacency


def compute_closure(roots, adjacency):
    """Transitive closure of the resource reference graph, seeded from roots.

    Only retrieved URIs (present as adjacency keys) belong to the closure; a
    referenced-but-not-retrieved URI is reported as unresolved instead.
    Returns a list in lexical order.
    """
    seen = set()
    root_set = set(roots)
    stack = [u for u in roots if u in adjacency or u in root_set]
    while stack:
        uri = stack.pop()
        if uri in seen:
            continue
        if uri not in adjacency:
            continue
        seen.add(uri)
        for target in sorted(adjacency.get(uri, ())):
            if target not in seen:
                stack.append(target)
    return sorted(seen)


def compute_unresolved(resource_uris, adjacency):
    """URIs referenced but not present among the retrieved resources."""
    referenced = set()
    for targets in adjacency.values():
        referenced.update(targets)
    return sorted(referenced - set(resource_uris))


def recompute_evidence(roots, resources):
    """Recompute closure and unresolved sets from resources records.

    Returns ``(closure_sorted, unresolved_sorted)`` in lexical order.
    """
    adjacency = adjacency_from_resources(resources)
    resource_uris = {r.get("uri") for r in resources}
    closure = compute_closure(list(roots), adjacency)
    unresolved = compute_unresolved(resource_uris, adjacency)
    return closure, unresolved


# ---------------------------------------------------------------------------
# Evidence schema helpers (shared by validator and replay)
# ---------------------------------------------------------------------------

def load_evidence(path):
    """Read an evidence file into a Python object."""
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def evidence_schema_errors(evidence, warn=_default_warn):
    """Validate the exact eight-array evidence schema; return error strings.

    Covers the eight top-level keys (unknown keys rejected), per-key types,
    resource-record required fields, dependency-record schemas, and the
    semantic_sources / local_citations / workflow_stages /
    case_study_citations / manual_review record schemas.  Domain rules
    (exact roots, closure consistency, parent_uri null-only-for-roots, etc.)
    are applied by the validator and replay callers.
    """
    errors = []
    if not isinstance(evidence, dict):
        return ["evidence is not a JSON object"]
    keys = list(evidence.keys())
    if len(keys) != len(EVIDENCE_KEYS) or set(keys) != set(EVIDENCE_KEYS):
        errors.append(
            "evidence top-level keys must be exactly %d: %s (got %s)"
            % (len(EVIDENCE_KEYS), ", ".join(EVIDENCE_KEYS),
               ", ".join(sorted(keys))))
        return errors

    # roots
    roots = evidence["roots"]
    if not isinstance(roots, list) or not all(
            isinstance(r, str) for r in roots):
        errors.append("roots must be a list of strings")

    # resources records
    resources = evidence["resources"]
    if not isinstance(resources, list):
        errors.append("resources must be a list")
    else:
        seen_uris = set()
        for index, record in enumerate(resources):
            label = "resources[%d]" % index
            if not isinstance(record, dict):
                errors.append("%s must be an object" % label)
                continue
            required = ("uri", "parent_uri", "retrieval_status", "content",
                        "content_sha256", "discovered_references")
            for key in required:
                if key not in record:
                    errors.append("%s missing key %r" % (label, key))
            uri = record.get("uri")
            if not isinstance(uri, str) or not uri:
                errors.append("%s uri must be a non-empty string" % label)
            elif uri in seen_uris:
                errors.append("%s duplicate uri %r" % (label, uri))
            seen_uris.add(uri)
            parent = record.get("parent_uri")
            if parent is not None and not isinstance(parent, str):
                errors.append("%s parent_uri must be a string or null" % label)
            status = record.get("retrieval_status")
            if status not in RETRIEVAL_STATUSES:
                errors.append("%s retrieval_status must be one of %s"
                              % (label, ", ".join(RETRIEVAL_STATUSES)))
            if not isinstance(record.get("content"), str):
                errors.append("%s content must be a string" % label)
            sha = record.get("content_sha256")
            if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}",
                                                            sha or ""):
                errors.append("%s content_sha256 must be 64 lowercase hex"
                              % label)
            refs = record.get("discovered_references")
            if not isinstance(refs, list):
                errors.append("%s discovered_references must be a list"
                              % label)
            else:
                for rindex, ref in enumerate(refs):
                    rlabel = "%s.discovered_references[%d]" % (label, rindex)
                    if not isinstance(ref, dict):
                        errors.append("%s must be an object" % rlabel)
                        continue
                    target = ref.get("target")
                    if not isinstance(target, str) or \
                            not target.startswith(POLYTOKEN_SCHEME):
                        errors.append("%s target must be a polytoken:// uri"
                                      % rlabel)
                    source = ref.get("source")
                    if source not in DEP_SOURCES:
                        errors.append("%s source must be one of %s"
                                      % (rlabel, ", ".join(DEP_SOURCES)))
                    line = ref.get("line")
                    if not isinstance(line, int) or isinstance(line, bool) \
                            or line < 1:
                        errors.append("%s line must be a positive integer"
                                      % rlabel)

    # unresolved_references
    unresolved = evidence["unresolved_references"]
    if not isinstance(unresolved, list) or not all(
            isinstance(u, str) for u in unresolved):
        errors.append("unresolved_references must be a list of strings")

    # semantic_sources
    sem = evidence["semantic_sources"]
    if not isinstance(sem, list):
        errors.append("semantic_sources must be a list")
    else:
        for index, record in enumerate(sem):
            label = "semantic_sources[%d]" % index
            if not isinstance(record, dict):
                errors.append("%s must be an object" % label)
                continue
            if set(record) != set(SEMANTIC_SOURCE_FIELDS):
                errors.append("%s fields must be exactly %s" %
                              (label, ", ".join(SEMANTIC_SOURCE_FIELDS)))
            for key in SEMANTIC_SOURCE_FIELDS:
                if not isinstance(record.get(key), str) or not record[key].strip():
                    errors.append("%s %r must be a non-empty string" % (label, key))
            if record.get("evidence_class") not in EVIDENCE_CLASSES:
                errors.append("%s evidence_class must be one of %s" %
                              (label, ", ".join(EVIDENCE_CLASSES)))

    # local_citations
    local = evidence["local_citations"]
    if not isinstance(local, list):
        errors.append("local_citations must be a list")
    else:
        for index, record in enumerate(local):
            label = "local_citations[%d]" % index
            if not isinstance(record, dict) or \
                    not isinstance(record.get("path"), str) or \
                    not record["path"].strip():
                errors.append("%s must be an object with a non-empty 'path'"
                              % label)

    # workflow_stages
    stages = evidence["workflow_stages"]
    if not isinstance(stages, list):
        errors.append("workflow_stages must be a list")
    else:
        for index, record in enumerate(stages):
            label = "workflow_stages[%d]" % index
            if not isinstance(record, dict):
                errors.append("%s must be an object" % label)
                continue
            for key in ("stage", "source_uri"):
                if not isinstance(record.get(key), str):
                    errors.append("%s %r must be a string" % (label, key))
            ids = record.get("semantic_ids")
            if not isinstance(ids, list) or not all(
                    isinstance(i, str) for i in ids):
                errors.append("%s semantic_ids must be a list of strings"
                              % label)

    # case_study_citations
    cases = evidence["case_study_citations"]
    if not isinstance(cases, list):
        errors.append("case_study_citations must be a list")
    else:
        for index, record in enumerate(cases):
            label = "case_study_citations[%d]" % index
            if not isinstance(record, dict):
                errors.append("%s must be an object" % label)
                continue
            for key in ("label", "uri", "status"):
                if not isinstance(record.get(key), str):
                    errors.append("%s %r must be a string" % (label, key))
            if record.get("status") not in CASE_STATUSES:
                errors.append("%s status must be one of %s"
                              % (label, ", ".join(CASE_STATUSES)))

    # manual_review
    manual = evidence["manual_review"]
    if not isinstance(manual, list):
        errors.append("manual_review must be a list")
    else:
        for index, record in enumerate(manual):
            label = "manual_review[%d]" % index
            if not isinstance(record, dict):
                errors.append("%s must be an object" % label)
                continue
            for key in ("id", "status", "note"):
                if not isinstance(record.get(key), str):
                    errors.append("%s %r must be a string" % (label, key))
    return errors


# ---------------------------------------------------------------------------
# CLI (used by hermetic subprocess parser tests)
# ---------------------------------------------------------------------------

def _cli(argv):
    if len(argv) != 2 or argv[0] != "--scan":
        sys.stderr.write(
            "usage: portability_evidence_parser.py --scan CONTENT.txt\n")
        return 2
    warnings = []

    def collect(msg):
        warnings.append(msg)

    with open(argv[1], encoding="utf-8") as handle:
        scan = scan_content(handle.read(), collect)
    for msg in warnings:
        print("warning: %s" % msg, file=sys.stderr)
    for record in references_from_scan(scan):
        print("%s %s (line %d)"
              % (record["target"], record["source"], record["line"]))
    if warnings:
        print("parser: %d warning(s)" % len(warnings), file=sys.stderr)
        return 1
    print("parser: %d dependency(s) scanned cleanly"
          % len(scan["references"]))
    return 0


def hash_content(text):
    """SHA-256 (hex) of a content string's UTF-8 bytes (raw digest)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
