#!/usr/bin/env python3
"""Validator for the portability audit (offline, stdlib-only).

Validates the three-portability-artifact triple::

    validate_portability_audit.py AUDIT.md EVIDENCE.json ROADMAP.md

The audit document, the evidence JSON, and the roadmap must be mutually
consistent.  The validator re-scans every retrieved resource's content with
the shared parser (``portability_evidence_parser``), so any malformed or
unsupported token surfaces as a deterministic ``parser warning: ...`` line
on stderr -- byte-identical to the warnings ``replay_portability_evidence.py``
emits for the same evidence.

Checks (each maps to a testable category):

* the exact ten ``##`` required headings, in order (an optional ``#`` title
  may precede)
* the capability-by-capability equivalence matrix: exactly the 12 capability
  IDs, one row each, a valid verdict, and a semantic-ID assignment whose
  union is exactly the 23 semantic IDs
* at most 3 RECOMMENDATION markers, each with the five fields
  benefit / touched_files / mechanism / testability / success_measurement
* the exact eight top-level evidence arrays (unknown keys rejected) and every
  nested record schema
* the exact six roots; root ``parent_uri`` null only
* closure / unresolved consistency (recomputed and compared)
* the 23 exact semantic IDs and their capability / evidence-uri assignments
* workflow_stages, case-study citation, and local-citation field semantics
* manual review: the five exact IDs (WF-1 WF-2 CASE-1 SRC-1 SRC-2), all pass
* cited paths / URIs / URLs, and roadmap path + status consistency

Exit codes: 0 valid, 1 invalid, 2 usage.
"""
import hashlib
import json
import os
import re
import sys
from urllib.parse import urlparse

from portability_evidence_parser import (
    CAPABILITY_IDS,
    CASE_STATUSES,
    EXPECTED_ROOTS,
    MANUAL_REVIEW_IDS,
    POLYTOKEN_SCHEME,
    SEMANTIC_IDS,
    SEMANTIC_SOURCE_FIELDS,
    SEMANTIC_CAPABILITIES,
    EVIDENCE_CLASSES,
    evidence_schema_errors,
    recompute_evidence,
    references_from_scan,
    scan_content,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ---------------------------------------------------------------------------
# Audit-domain constants (the "exact" IDs)
# ---------------------------------------------------------------------------

# Exact ordered set of required level-2 headings.
REQUIRED_HEADINGS = (
    "Executive answer",
    "Scope, assumptions, and evidence quality",
    "Polytoken runtime/workflow model",
    "Existing ed3d/Copilot workflow model",
    "Capability-by-capability equivalence matrix",
    "Quality-impact/cost ranking",
    "Case study: research failure and missing controls",
    "Recommended MVP ports, deferred work, and explicit non-goals",
    "Compatibility and version risks",
    "Source index",
)

# Matrix columns (header) for the equivalence matrix table.
MATRIX_HEADER = ("Capability", "Polytoken mechanism",
                 "Copilot CLI equivalent", "Verdict", "Semantic IDs")
VALID_VERDICTS = ("portable", "partial", "gap")

MAX_RECOMMENDATIONS = 3
RECOMMENDATION_FIELDS = ("benefit", "touched_files", "mechanism",
                         "testability", "success_measurement")

WARN_PREFIX = "parser warning:"


# ---------------------------------------------------------------------------
# Markdown helpers
# ---------------------------------------------------------------------------

def level2_headings(text):
    """Return the ordered list of level-2 heading titles (without hashes)."""
    headings = []
    for line in text.splitlines():
        match = re.match(r"^##\s+(.*)$", line)
        if match:
            headings.append(match.group(1).strip())
    return headings


def split_sections(text):
    """Split markdown text into level-2-heading-keyed sections."""
    sections = {}
    current = None
    for line in text.splitlines():
        match = re.match(r"^(#{1,6})\s+(.*)$", line)
        if match:
            current = match.group(2).strip()
            sections.setdefault(current, [])
            continue
        if current is not None:
            sections[current].append(line)
    return {key: "\n".join(value) for key, value in sections.items()}


def classify_target(target):
    """Classify a citation target as uri, url, or path."""
    if target.startswith(POLYTOKEN_SCHEME):
        return "uri"
    if re.match(r"https?://", target):
        return "url"
    return "path"


def valid_url(target):
    parsed = urlparse(target)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


# ---------------------------------------------------------------------------
# Audit section parsers
# ---------------------------------------------------------------------------

def parse_matrix(section, errors):
    """Parse the equivalence-matrix table; require the 12 rows + fields."""
    rows = [line for line in section.splitlines()
            if line.strip().startswith("|")]
    if not rows:
        errors.append("capability matrix table missing")
        return {}
    header = [c.strip() for c in rows[0].strip("|").split("|")]
    if tuple(header) != MATRIX_HEADER:
        errors.append("capability matrix header must be %s (got %s)"
                      % (" | ".join(MATRIX_HEADER), " | ".join(header)))
    matrix = {}
    for row in rows[1:]:
        cells = [c.strip() for c in row.strip("|").split("|")]
        if all(re.fullmatch(r"-{1,}", c) for c in cells):  # separator
            continue
        if len(cells) != len(MATRIX_HEADER):
            errors.append("matrix row must have %d fields: %r"
                          % (len(MATRIX_HEADER), " | ".join(cells)))
            continue
        cid, mechanism, equiv, verdict, semantic_cell = cells
        if cid not in CAPABILITY_IDS:
            errors.append("matrix row has unknown capability id %r" % cid)
        if cid in matrix:
            errors.append("matrix duplicate capability id %r" % cid)
        if not mechanism:
            errors.append("matrix %s has an empty mechanism" % cid)
        if not equiv:
            errors.append("matrix %s has an empty Copilot equivalent" % cid)
        if verdict not in VALID_VERDICTS:
            errors.append("matrix %s verdict %r must be one of %s"
                          % (cid, verdict, ", ".join(VALID_VERDICTS)))
        sids = [s for s in re.split(r"[,\s]+", semantic_cell) if s]
        for s in sids:
            if s not in SEMANTIC_IDS:
                errors.append("matrix %s references unknown semantic id %r"
                              % (cid, s))
        matrix[cid] = {"mechanism": mechanism, "equiv": equiv,
                       "verdict": verdict, "semantic_ids": set(sids)}
    if set(matrix) != set(CAPABILITY_IDS):
        errors.append("capability matrix must contain exactly the 12 "
                      "capability ids (%s)" % ", ".join(CAPABILITY_IDS))
    return matrix


def parse_recommendations(section, errors):
    """Parse RECOMMENDATION markers; require <=3, each with 5 fields."""
    recs = []
    current = None
    for line in section.splitlines():
        marker = re.match(r"^-\s*\*\*RECOMMENDATION[:\s]*(.*?)(?:\*\*)?\s*$",
                          line)
        if marker:
            current = {"title": marker.group(1).strip(), "fields": {}}
            recs.append(current)
            continue
        field = re.match(r"^\s*-\s*([a-z_]+):\s*(.+)$", line)
        if field and current is not None:
            key, value = field.group(1).strip(), field.group(2).strip()
            if key in current["fields"]:
                errors.append("recommendation %r duplicates field %r" %
                              (current["title"], key))
            current["fields"][key] = value
    if len(recs) > MAX_RECOMMENDATIONS:
        errors.append("too many RECOMMENDATION markers (%d > %d)"
                      % (len(recs), MAX_RECOMMENDATIONS))
    for rec in recs:
        if not rec["title"]:
            errors.append("recommendation title must not be empty")
        for key in RECOMMENDATION_FIELDS:
            if key not in rec["fields"] or not rec["fields"][key]:
                errors.append("recommendation %r missing field %r"
                              % (rec["title"], key))
    return recs


def parse_scope_declarations(section, errors):
    """Extract Evidence / Roadmap declaration lines from the Scope section."""
    decl = {"evidence": None, "roadmap_file": None,
            "roadmap_status": None, "roadmap_paths": []}
    for line in section.splitlines():
        match = re.match(r"^Evidence:\s*(\S+)\s*$", line)
        if match:
            decl["evidence"] = match.group(1)
            continue
        match = re.match(r"^Roadmap file:\s*(\S+)\s*$", line)
        if match:
            decl["roadmap_file"] = match.group(1)
            continue
        match = re.match(r"^Roadmap status:\s*(\S.*)$", line)
        if match:
            decl["roadmap_status"] = match.group(1).strip()
            continue
        match = re.match(r"^Roadmap path:\s*(\S+)\s*$", line)
        if match:
            decl["roadmap_paths"].append(match.group(1))
    if decl["evidence"] is None:
        errors.append("Scope must declare `Evidence: <file>`")
    if decl["roadmap_file"] is None:
        errors.append("Scope must declare `Roadmap file: <file>`")
    if decl["roadmap_status"] is None:
        errors.append("Scope must declare `Roadmap status: <keyword>`")
    return decl


def parse_source_index(section, errors):
    """Parse `- <label>: <target>` bullets from the Source index."""
    citations = []
    for line in section.splitlines():
        if not line.strip():
            continue
        match = re.match(r"^-\s*([^:]+):\s*(\S+)\s*$", line)
        if not match:
            errors.append("source index line not in `- <label>: <target>` "
                          "form: %r" % line.strip())
            continue
        label, target = match.group(1).strip(), match.group(2).strip()
        if not label:
            errors.append("source index citation has an empty label")
        citations.append({"label": label, "target": target})
    return citations


def parse_case_study_citations(section, errors):
    """Parse `- <label>: <target> (<status>)` bullets from the case study."""
    citations = []
    pattern = re.compile(r"^-\s*(.+?):\s*(\S+)\s*\((\w+)\)\s*$")
    for line in section.splitlines():
        if not line.strip().startswith("-"):
            continue
        match = pattern.match(line)
        if not match:
            errors.append("case study citation not in `- <label>: <target> "
                          "(<status>)` form: %r" % line.strip())
            continue
        label, target, status = match.groups()
        if status not in CASE_STATUSES:
            errors.append("case study citation status %r must be one of %s"
                          % (status, ", ".join(CASE_STATUSES)))
        citations.append({"label": label.strip(), "target": target,
                          "status": status})
    return citations


# ---------------------------------------------------------------------------
# Evidence checks
# ---------------------------------------------------------------------------

def _resolve(uri, resource_uris, unresolved):
    return uri in resource_uris or uri in unresolved


def validate_evidence(evidence, matrix, warn):
    """Validate evidence schema + domain rules; return (errors, context)."""
    errors = list(evidence_schema_errors(evidence, warn))
    context = {}

    roots = evidence.get("roots")
    if list(roots) != list(EXPECTED_ROOTS):
        errors.append("roots must be exactly the six expected roots, in "
                      "canonical order")

    resources = evidence.get("resources", [])
    resource_uris = {r.get("uri") for r in resources if isinstance(r, dict)}
    for root in EXPECTED_ROOTS:
        if root not in resource_uris:
            errors.append("root %r not present in resources" % root)

    # Root parent_uri null only.
    for record in resources:
        if not isinstance(record, dict):
            continue
        uri = record.get("uri")
        parent = record.get("parent_uri")
        is_root = uri in EXPECTED_ROOTS
        if is_root and parent is not None:
            errors.append("root %r must have parent_uri null, got %r"
                          % (uri, parent))
        if not is_root and parent is None:
            errors.append("non-root resource %r must have a non-null "
                          "parent_uri" % uri)
        if not is_root and parent is not None and \
                parent not in resource_uris:
            errors.append("resource %r parent_uri %r is not a resource"
                          % (uri, parent))

    # Re-scan each resource content; compare to recorded references.
    for record in sorted(resources, key=lambda r: r.get("uri", "")):
        uri = record.get("uri")
        if not isinstance(uri, str):
            continue
        content = record.get("content", "")
        if isinstance(content, str):
            actual_hash = hashlib.sha256(
                content.encode("utf-8")).hexdigest()
            if actual_hash != record.get("content_sha256"):
                errors.append("content_sha256 mismatch for %r (recorded %s, actual %s)" %
                              (uri, record.get("content_sha256"), actual_hash))
        scan = scan_content(content, warn)
        expected = sorted(record.get("discovered_references", []),
                          key=lambda r: (r.get("target", ""),
                                         r.get("line", 0),
                                         r.get("source", "")))
        if expected != references_from_scan(scan):
            errors.append("recorded discovered_references for %r do not "
                          "match a re-scan of its content" % uri)

    # Closure / unresolved recompute + comparison.
    recomputed_closure, recomputed_unresolved = recompute_evidence(
        list(roots), resources)
    if set(recomputed_closure) != set(resource_uris):
        errors.append("recomputed closure must equal the resource uri set")
    recorded_unresolved = evidence.get("unresolved_references", [])
    if list(recorded_unresolved) != recomputed_unresolved:
        errors.append("unresolved_references does not match recomputed "
                      "unresolved set")
    for uri in recorded_unresolved:
        if not isinstance(uri, str) or not uri.startswith(POLYTOKEN_SCHEME):
            errors.append("unresolved entry must be a polytoken:// uri: %r"
                          % uri)

    # semantic_sources: 23 exact ids, capabilities, and resolved evidence.
    sem = evidence.get("semantic_sources", [])
    sem_ids = {}
    sem_by_cap = {}
    for record in sem:
        if not isinstance(record, dict):
            continue
        sid = record.get("claim_id")
        cap = record.get("capability")
        uri = record.get("url")
        if set(record) != set(SEMANTIC_SOURCE_FIELDS):
            errors.append("semantic_sources %s fields must be exactly %s" %
                          (sid, ", ".join(SEMANTIC_SOURCE_FIELDS)))
        if isinstance(sid, str):
            sem_ids[sid] = record
            sem_by_cap.setdefault(cap, set()).add(sid)
            if cap != SEMANTIC_CAPABILITIES.get(sid):
                errors.append("semantic_sources %s has incorrect capability assignment" % sid)
        if cap not in CAPABILITY_IDS:
            errors.append("semantic_sources references unknown capability %r" % cap)
        if record.get("evidence_class") not in EVIDENCE_CLASSES:
            errors.append("semantic_sources %s has invalid evidence_class" % sid)
        # Claims classified unresolved must point at a captured unresolved dependency;
        # this prevents unrelated root prose from masquerading as grounding.
        if record.get("evidence_class") == "unresolved" and not _resolve(uri, set(), recorded_unresolved):
            errors.append("semantic_sources %s unresolved claim must reference an unresolved dependency" % sid)
        if uri and not (_resolve(uri, resource_uris, recorded_unresolved) or valid_url(uri)): 
            errors.append("semantic_sources %s references uri %r that is neither retrieved, unresolved, nor a valid URL" % (sid, uri))
    if set(sem_ids) != set(SEMANTIC_IDS):
        errors.append("semantic_sources must contain exactly the 23 semantic "
                      "ids (%s)" % ", ".join(SEMANTIC_IDS))
    # Cross-check with the audit matrix semantic assignment.
    for cap in CAPABILITY_IDS:
        if cap in matrix and \
                sem_by_cap.get(cap, set()) != matrix[cap]["semantic_ids"]:
            errors.append("matrix semantic assignment for %s disagrees with "
                          "semantic_sources" % cap)

    # workflow_stages field semantics.
    stages = evidence.get("workflow_stages", [])
    stage_ids = set()
    stage_roots = set()
    for record in stages:
        if not isinstance(record, dict):
            continue
        stage = record.get("stage")
        src = record.get("source_uri")
        ids = record.get("semantic_ids") or []
        if not stage:
            errors.append("workflow_stage has an empty stage name")
        if src not in EXPECTED_ROOTS:
            errors.append("workflow_stage source_uri %r is not one of the "
                          "six roots" % src)
        if not ids or any(i not in SEMANTIC_IDS for i in ids):
            errors.append("workflow_stage %r semantic_ids must be non-empty "
                          "and drawn from the 23 semantic ids" % stage)
        stage_ids.update(ids)
        stage_roots.add(src)
    if set(stage_ids) != set(SEMANTIC_IDS):
        errors.append("workflow_stages semantic_ids union must cover exactly "
                      "the 23 semantic ids")
    if stage_roots != set(EXPECTED_ROOTS):
        errors.append("workflow_stages must use every root as a source_uri "
                      "at least once")

    # case_study_citations field semantics.
    cases = evidence.get("case_study_citations", [])
    if not cases:
        errors.append("case_study_citations must not be empty")
    if not any(c.get("status") == "unresolved" for c in cases
               if isinstance(c, dict)):
        errors.append("case_study_citations must include at least one citation marked unresolved")
    airpods = [c for c in cases if isinstance(c, dict) and
               c.get("label") == "AirPods portability case study"]
    if len(airpods) != 1 or airpods[0].get("uri") != "polytoken://case-studies/airpods-portability.md" or airpods[0].get("status") != "unresolved":
        errors.append("AirPods case-study citation must identify the absent checkout artifact and be unresolved")
    for case in cases:
        if isinstance(case, dict) and case.get("status") == "observed":
            uri = case.get("uri")
            if not _resolve(uri, resource_uris, recorded_unresolved):
                errors.append("observed case-study source must resolve: %r" % uri)

    # manual_review: five exact ids, all passing.
    manual = evidence.get("manual_review", [])
    manual_ids = {}
    for record in manual:
        if isinstance(record, dict):
            manual_ids[record.get("id")] = record.get("status")
    if set(manual_ids) != set(MANUAL_REVIEW_IDS):
        errors.append("manual_review ids must be exactly %s"
                      % ", ".join(MANUAL_REVIEW_IDS))
    for mid in MANUAL_REVIEW_IDS:
        if manual_ids.get(mid) != "pass":
            errors.append("manual review %s must be 'pass' in evidence" % mid)

    context["resource_uris"] = resource_uris
    context["unresolved"] = recorded_unresolved
    return errors, context


def validate_local_citations(local, errors):
    """Every local_citations path must exist on disk."""
    for record in local:
        if not isinstance(record, dict):
            continue
        path = record.get("path")
        if not path:
            continue
        if not os.path.isfile(os.path.join(ROOT, path)):
            errors.append("local citation path does not exist: %r" % path)


def validate_source_index(citations, local_paths, context, errors):
    """Validate cited paths / URIs / URLs and required root citations."""
    resource_uris = context.get("resource_uris", set())
    unresolved = context.get("unresolved", [])
    targets = [c["target"] for c in citations]
    for root in EXPECTED_ROOTS:
        if root not in targets:
            errors.append("required citation for root %r missing" % root)
    for target in sorted(set(targets)):
        kind = classify_target(target)
        if kind == "path":
            if not os.path.isfile(os.path.join(ROOT, target)):
                errors.append("cited path does not exist: %r" % target)
        elif kind == "uri":
            if not _resolve(target, resource_uris, unresolved):
                errors.append("cited uri %r is neither retrieved nor "
                              "unresolved" % target)
        elif kind == "url":
            if not valid_url(target):
                errors.append("cited url is not syntactically valid: %r"
                              % target)
    # Every local_citations path must also be cited in the Source index.
    cited_paths = {c["target"] for c in citations
                   if classify_target(c["target"]) == "path"}
    for path in local_paths:
        if path not in cited_paths:
            errors.append("local citation %r not listed in Source index"
                          % path)


def validate_roadmap(roadmap_path, decl, errors):
    """Check roadmap file existence, status keyword, and referenced paths."""
    if not os.path.isfile(roadmap_path):
        errors.append("roadmap file does not exist: %r" % roadmap_path)
        return
    if decl["roadmap_file"] and \
            os.path.basename(roadmap_path) != decl["roadmap_file"]:
        errors.append("Scope Roadmap file %r does not match the roadmap "
                      "argument" % decl["roadmap_file"])
    with open(roadmap_path, encoding="utf-8") as handle:
        roadmap_text = handle.read()
    status = decl["roadmap_status"]
    if status == "audit complete 2026-09-01; implementation deferred":
        relevant = re.search(
            r"^[-*].*Polytoken ↔ ed3d-plugins prompt cross-pollination.*"
            r"audit complete 2026-09-01; implementation deferred",
            roadmap_text, re.MULTILINE)
        if not relevant:
            errors.append("roadmap status declaration not found in cross-pollination entry")
    elif status and status not in roadmap_text:
        errors.append("roadmap status keyword %r not found in roadmap"
                      % status)
    for path in decl["roadmap_paths"]:
        if not os.path.isfile(os.path.join(ROOT, path)):
            errors.append("roadmap path does not exist: %r" % path)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def validate(audit_path, evidence_path, roadmap_path, warn):
    """Run the full validation; return (errors, warnings)."""
    errors = []
    warnings = []

    if not os.path.isfile(audit_path):
        return ["audit file does not exist: %r" % audit_path], warnings
    with open(audit_path, encoding="utf-8") as handle:
        audit_text = handle.read()

    # Headings: the ten level-2 headings exactly (a `#` title may precede).
    headings = level2_headings(audit_text)
    if headings != list(REQUIRED_HEADINGS):
        errors.append("level-2 headings must be exactly %s in order"
                      % " ; ".join(REQUIRED_HEADINGS))

    sections = split_sections(audit_text)

    matrix = parse_matrix(
        sections.get("Capability-by-capability equivalence matrix", ""),
        errors)
    # Union of semantic ids across the matrix must be exactly the 23.
    if matrix:
        union = set()
        for row in matrix.values():
            union |= row["semantic_ids"]
        if union != set(SEMANTIC_IDS):
            errors.append("matrix semantic IDs union must be exactly the 23 "
                          "semantic ids")

    parse_recommendations(
        sections.get("Recommended MVP ports, deferred work, and explicit "
                     "non-goals", ""), errors)
    decl = parse_scope_declarations(
        sections.get("Scope, assumptions, and evidence quality", ""), errors)
    citations = parse_source_index(sections.get("Source index", ""), errors)
    audit_cases = parse_case_study_citations(
        sections.get("Case study: research failure and missing controls", ""),
        errors)

    # Evidence.
    if not os.path.isfile(evidence_path):
        return errors + ["evidence file does not exist: %r" % evidence_path], \
            warnings
    try:
        evidence = json.load(open(evidence_path, encoding="utf-8"))
    except ValueError as exc:
        return errors + ["evidence is not valid JSON: %s" % exc], warnings

    ev_errors, context = validate_evidence(evidence, matrix, warn)
    errors.extend(ev_errors)
    warnings.extend(warn.warnings if hasattr(warn, "warnings") else [])

    # Local citations + source index.
    local = evidence.get("local_citations", []) \
        if isinstance(evidence, dict) else []
    local_paths = [r.get("path") for r in local if isinstance(r, dict)]
    validate_local_citations(local, errors)
    validate_source_index(citations, local_paths, context, errors)

    # Case-study citations: evidence and audit must agree on (label, uri,
    # status).
    ev_cases = evidence.get("case_study_citations", []) \
        if isinstance(evidence, dict) else []
    ev_pairs = {(c.get("label"), c.get("uri"), c.get("status"))
                for c in ev_cases if isinstance(c, dict)}
    audit_pairs = {(c["label"], c["target"], c["status"])
                   for c in audit_cases}
    if ev_pairs != audit_pairs:
        errors.append("case study citations disagree between evidence and "
                      "audit")

    # Roadmap consistency.
    validate_roadmap(roadmap_path, decl, errors)

    return errors, warnings


class _WarnCollector(object):
    """Collect parser warnings in deterministic order."""
    def __init__(self):
        self.warnings = []

    def __call__(self, msg):
        self.warnings.append(msg)


def main(argv):
    if len(argv) != 3:
        sys.stderr.write(
            "usage: validate_portability_audit.py AUDIT.md EVIDENCE.json "
            "ROADMAP.md\n")
        return 2
    audit_path, evidence_path, roadmap_path = argv
    collector = _WarnCollector()
    errors, warnings = validate(audit_path, evidence_path, roadmap_path,
                                collector)
    for msg in warnings:
        print("%s %s" % (WARN_PREFIX, msg), file=sys.stderr)
    for err in errors:
        print("FAIL %s" % err)
    print("validation: %d error(s), %d parser warning(s)"
          % (len(errors), len(warnings)))
    if errors:
        return 1
    print("OK: portability audit is valid")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
