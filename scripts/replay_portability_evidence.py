#!/usr/bin/env python3
"""Replay recorded portability evidence without re-collecting (offline).

Imports the shared parser and re-drives the recorded evidence through the
same deterministic machinery, then checks that the current environment can
reproduce it byte-for-byte::

    replay_portability_evidence.py EVIDENCE.json

For every retrieved resource, in deterministic (lexical URI) order, the
replay invokes the exact ``polytoken vfs cat <URI>`` command, compares the
SHA-256 of the raw stdout bytes against the recorded ``content_sha256``,
re-scans each resource's content with the shared parser, and recomputes the
reference-graph closure and unresolved sets.  URL references are validated
for syntax and metadata only -- no network fetch is ever performed.

A test-only override replaces the ``polytoken vfs cat`` command line via
the ``PORTABILITY_VFS_CAT_COMMAND`` environment variable (the URI is
appended as the final argument).  This keeps tests hermetic with no
installed ``polytoken`` binary.

Exit codes: 0 replayed cleanly, 1 any mismatch/error, 2 usage.
"""
import hashlib
import json
import os
import shlex
import subprocess
import sys
from urllib.parse import urlparse

from portability_evidence_parser import (
    EVIDENCE_KEYS,
    POLYTOKEN_SCHEME,
    evidence_schema_errors,
    hash_content,
    recompute_evidence,
    references_from_scan,
    scan_content,
    CAPABILITY_IDS,
    SEMANTIC_CAPABILITIES,
)
from validate_portability_audit import validate_evidence

CAT_COMMAND_ENV = "PORTABILITY_VFS_CAT_COMMAND"
WARN_PREFIX = "parser warning:"


def vfs_cat_command(uri):
    """Return the argv for fetching ``uri`` from the VFS.

    Defaults to the exact ``polytoken vfs cat <uri>``.  When
    ``PORTABILITY_VFS_CAT_COMMAND`` is set, that command line is split and
    the URI is appended as the final argument (test-only override).
    """
    override = os.environ.get(CAT_COMMAND_ENV)
    if override:
        return shlex.split(override) + [uri]
    return ["polytoken", "vfs", "cat", uri]


def fetch_resource(uri):
    """Run the VFS cat command for ``uri``; return (ok, raw_bytes, error)."""
    try:
        proc = subprocess.run(vfs_cat_command(uri), capture_output=True,
                              check=False)
    except OSError as exc:
        return False, b"", "failed to run vfs cat: %s" % exc
    if proc.returncode != 0:
        return False, b"", "vfs cat exited %d: %s" % (
            proc.returncode, proc.stderr.decode("utf-8", "replace").strip())
    return True, proc.stdout, None


def _uri_kind(uri):
    if uri.startswith(POLYTOKEN_SCHEME):
        return "uri"
    if urlparse(uri).scheme in ("http", "https"):
        return "url"
    return "other"


def validate_url_metadata(cases, errors):
    """Offline-only URL syntax validation for case-study citation uris."""
    for record in cases:
        if not isinstance(record, dict):
            continue
        uri = record.get("uri")
        if not isinstance(uri, str) or _uri_kind(uri) != "url":
            continue
        parsed = urlparse(uri)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            errors.append("case study citation url is not syntactically "
                          "valid: %r" % uri)


def main(argv):
    if len(argv) != 1:
        sys.stderr.write(
            "usage: replay_portability_evidence.py EVIDENCE.json\n")
        return 2
    path = argv[0]

    if not os.path.isfile(path):
        print("FAIL evidence file does not exist: %r" % path)
        return 1
    try:
        evidence = json.load(open(path, encoding="utf-8"))
    except ValueError as exc:
        print("FAIL evidence is not valid JSON: %s" % exc)
        return 1

    warnings = []

    def collect(msg):
        warnings.append(msg)

    errors = list(evidence_schema_errors(evidence, collect))

    # Replay must enforce the complete audit-domain contract, not merely the
    # transport/hash portions. Reconstruct matrix assignments from the
    # evidence's semantic_sources records, rather than a canonical audit-independent mapping.
    matrix = {cap: {"semantic_ids": set()} for cap in CAPABILITY_IDS}
    for record in evidence.get("semantic_sources", []) if isinstance(evidence, dict) else []:
        if isinstance(record, dict):
            sid = record.get("claim_id")
            cap = record.get("capability")
            if cap in matrix:
                matrix[cap]["semantic_ids"].add(sid)
    # Suppress the domain pass's parser callbacks; replay scans below are the
    # single warning-producing pass, preserving validator/replay parity.
    domain_errors, _ = validate_evidence(evidence, matrix, lambda msg: None)
    errors.extend(domain_errors)

    resources = evidence.get("resources", []) if isinstance(evidence, dict) \
        else []
    roots = evidence.get("roots", []) if isinstance(evidence, dict) else []

    # 1) Hash replay in deterministic (lexical URI) order.
    for record in sorted(resources, key=lambda r: r.get("uri", "")):
        uri = record.get("uri")
        if not isinstance(uri, str):
            continue
        ok, raw, err = fetch_resource(uri)
        if not ok:
            errors.append("could not retrieve %r: %s" % (uri, err))
            continue
        actual = hashlib.sha256(raw).hexdigest()
        recorded = record.get("content_sha256")
        if actual != recorded:
            errors.append("sha256 mismatch for %r (recorded %s, actual %s)"
                          % (uri, recorded, actual))

    # 2) Re-scan content with the shared parser; compare to recorded refs.
    for record in sorted(resources, key=lambda r: r.get("uri", "")):
        uri = record.get("uri")
        if not isinstance(uri, str):
            continue
        scan = scan_content(record.get("content", ""), collect)
        expected = sorted(record.get("discovered_references", []),
                          key=lambda r: (r.get("target", ""),
                                         r.get("line", 0),
                                         r.get("source", "")))
        if expected != references_from_scan(scan):
            errors.append("recorded discovered_references for %r do not "
                          "match a re-scan of its content" % uri)

    # 3) Recompute closure + unresolved and compare.
    recomputed_closure, recomputed_unresolved = recompute_evidence(
        list(roots), resources)
    if set(recomputed_closure) != {r.get("uri") for r in resources
                                   if isinstance(r, dict)}:
        errors.append("recomputed closure does not match the resource uri "
                      "set")
    if list(evidence.get("unresolved_references", [])) != \
            recomputed_unresolved:
        errors.append("recomputed unresolved does not match recorded "
                      "unresolved_references")

    # 4) Offline URL syntax validation for case-study citations.
    validate_url_metadata(evidence.get("case_study_citations", []), errors)

    # 5) Report warnings on stderr (deterministic, identical to validator).
    for msg in warnings:
        print("%s %s" % (WARN_PREFIX, msg), file=sys.stderr)

    for err in errors:
        print("FAIL %s" % err)
    print("replay: %d retrieved, %d error(s), %d parser warning(s)"
          % (len(resources), len(errors), len(warnings)))
    if errors:
        return 1
    print("OK: recorded evidence replays cleanly")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
