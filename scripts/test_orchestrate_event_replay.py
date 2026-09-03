#!/usr/bin/env python3
"""Deterministic event replay tests for the ed3d-orchestrate approval gate.

Replays JSONL event streams (mirroring Copilot CLI's per-session events.jsonl)
through the plan-review -> approval -> builder-dispatch protocol and verifies,
purely at the protocol layer (a protocol-only seam; no runtime enforcement is
claimed), that:

  * every event is strictly schema-valid (exact payload key set, types, enums),
  * seq values are strictly increasing across the stream,
  * event types are recognized,
  * a persisted ``gate.approval == "granted"`` precedes every builder dispatch
    (``builder.task``) and every ``subagent.started``,
  * builder dispatches correlate to their started/completed subagents by
    ``toolCallId``,
  * the builder-dispatch tool name is flexible (alternate tool names such as
    ``Task`` are accepted; the protocol seam is the event type, not the tool).

Each fixture under scripts/fixtures/orchestrate-events/ is replayed and its
verdict compared against the expected outcome encoded in EXPECTED. The script
is deterministic, stdlib-only, writes nothing, dispatches no subagents, and
modifies no workflow docs or version files.

Usage:
  python3 scripts/test_orchestrate_event_replay.py
      Replay every fixture and report a pass/fail summary.
  python3 scripts/test_orchestrate_event_replay.py <fixture-name-or-path>
      Replay a single fixture with an event-by-event trace (clear CLI output).
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES_DIR = ROOT / "scripts/fixtures/orchestrate-events"


class Verdict(str, Enum):
    OK = "OK"  # legal protocol trace
    VIOLATION = "VIOLATION"  # protocol violation (approval ordering)
    MALFORMED = "MALFORMED"  # stream is malformed (schema/seq/type)


# --------------------------------------------------------------------------- #
# Event schema: recognized type -> (required key -> type, key -> allowed enum)
# --------------------------------------------------------------------------- #
_SCHEMAS = {
    "gate.approval": (
        {"approval": str, "path": str},
        {"approval": {"granted", "pending", "denied"}},
    ),
    "builder.task": (
        {"task": int, "tool": str, "toolCallId": str},
        {},
    ),
    "subagent.started": (
        {"agentName": str, "toolCallId": str, "model": str},
        {},
    ),
    "subagent.completed": (
        {"agentName": str, "toolCallId": str, "totalTokens": int},
        {},
    ),
    "tool.execution_start": ({"toolCallId": str, "tool": str}, {}),
    "tool.execution_complete": ({"toolCallId": str, "tool": str}, {}),
    "assistant.turn_start": ({"turn": int}, {}),
    "assistant.turn_end": ({"turn": int}, {}),
    "assistant.message": ({"role": str, "content": str}, {}),
    "session.model_change": ({"from": str, "to": str}, {}),
    "session.usage_checkpoint": ({"totalTokens": int}, {}),
    "skill.invoked": ({"skill": str}, {}),
    "permission.requested": ({"toolCallId": str}, {}),
    "permission.completed": ({"toolCallId": str}, {}),
    "hook.start": ({"hook": str}, {}),
    "hook.end": ({"hook": str}, {}),
}


def _validate_event(event: dict, prev_seq: int):
    """Return an error string if event is invalid, else None (strict schema)."""
    if not isinstance(event, dict):
        return "event is not a JSON object"
    for key in ("seq", "type", "payload"):
        if key not in event:
            return f"missing top-level key {key!r}"
    seq = event["seq"]
    if isinstance(seq, bool) or not isinstance(seq, int):
        return "seq must be an integer"
    if seq <= prev_seq:
        return f"seq not strictly increasing ({seq} after {prev_seq})"
    etype = event["type"]
    if not isinstance(etype, str):
        return "type must be a string"
    if etype not in _SCHEMAS:
        return f"unrecognized event type {etype!r}"
    payload = event["payload"]
    if not isinstance(payload, dict):
        return "payload must be a JSON object"
    required, enums = _SCHEMAS[etype]
    missing = set(required) - set(payload)
    extra = set(payload) - set(required)
    if missing:
        return f"payload missing required key(s) {sorted(missing)}"
    if extra:
        return f"payload has unexpected key(s) {sorted(extra)}"
    for key, typ in required.items():
        val = payload[key]
        if typ is int and (isinstance(val, bool) or not isinstance(val, int)):
            return f"payload.{key} must be an integer, got {type(val).__name__}"
        if typ is str and not isinstance(val, str):
            return f"payload.{key} must be a string, got {type(val).__name__}"
    for key, allowed in enums.items():
        if payload[key] not in allowed:
            return (
                f"payload.{key} must be one of {sorted(allowed)}, "
                f"got {payload[key]!r}"
            )
    return None


# --------------------------------------------------------------------------- #
# Replayer
# --------------------------------------------------------------------------- #
@dataclass
class ReplayResult:
    verdict: Verdict = Verdict.OK
    reason: str = ""
    gate: str = "pending"  # persisted gate.approval
    path: str = ""
    events_processed: int = 0
    violations: list = field(default_factory=list)
    notes: list = field(default_factory=list)


class Replayer:
    """Replays an event stream and records protocol verdicts at the seam."""

    def __init__(self):
        self.gate = "pending"  # persisted gate.approval
        self.path = ""
        self._builders = {}  # toolCallId -> task number (dispatched, uncorrelated yet)
        self._started = set()  # toolCallIds with a subagent.started

    def replay(self, events: list) -> ReplayResult:
        result = ReplayResult()
        prev_seq = -1
        for idx, event in enumerate(events):
            err = _validate_event(event, prev_seq)
            if err is not None:
                result.verdict = Verdict.MALFORMED
                result.reason = f"event {idx + 1} (seq {event.get('seq')}): {err}"
                result.events_processed = idx
                return result
            prev_seq = event["seq"]
            result.events_processed = idx + 1
            etype, payload = event["type"], event["payload"]

            if etype == "gate.approval":
                self.gate = payload["approval"]
                self.path = payload["path"]
                if self.gate == "granted":
                    result.notes.append(
                        f"seq {event['seq']}: gate.approval granted (path={self.path!r})"
                    )
            elif etype == "builder.task":
                if self.gate != "granted":
                    result.violations.append(
                        f"seq {event['seq']}: builder.task (task {payload['task']}) "
                        f"dispatched while gate.approval={self.gate!r} (not granted)"
                    )
                else:
                    self._builders[payload["toolCallId"]] = payload["task"]
                    result.notes.append(
                        f"seq {event['seq']}: builder.task {payload['task']} via tool "
                        f"{payload['tool']!r} toolCallId {payload['toolCallId']}"
                    )
            elif etype == "subagent.started":
                if self.gate != "granted":
                    result.violations.append(
                        f"seq {event['seq']}: subagent.started ({payload['agentName']}) "
                        f"while gate.approval={self.gate!r} (not granted)"
                    )
                else:
                    self._started.add(payload["toolCallId"])
                    if payload["toolCallId"] in self._builders:
                        result.notes.append(
                            f"seq {event['seq']}: subagent {payload['agentName']} "
                            f"correlated to builder.task "
                            f"{self._builders[payload['toolCallId']]} "
                            f"(toolCallId {payload['toolCallId']})"
                        )
                    else:
                        result.notes.append(
                            f"seq {event['seq']}: subagent {payload['agentName']} "
                            f"started (toolCallId {payload['toolCallId']}, "
                            "not a tracked builder dispatch)"
                        )
            elif etype == "subagent.completed":
                if payload["toolCallId"] in self._builders:
                    task = self._builders.pop(payload["toolCallId"])
                    result.notes.append(
                        f"seq {event['seq']}: subagent {payload['agentName']} "
                        f"(builder.task {task}) completed"
                    )
            # All other recognized types are informational; no protocol effect.

        # Correlation completeness: any dispatched builder never started?
        for cid, task in self._builders.items():
            if cid not in self._started:
                result.notes.append(
                    f"builder.task {task} (toolCallId {cid}) has no matching "
                    "subagent.started (uncorrelated)"
                )

        if result.violations:
            result.verdict = Verdict.VIOLATION
            result.reason = "; ".join(result.violations[:2])
            if len(result.violations) > 2:
                result.reason += f" (+{len(result.violations) - 2} more)"
        else:
            result.reason = (
                f"protocol trace legal; {result.events_processed} events, "
                f"gate.approval={self.gate!r}"
            )
        return result


# --------------------------------------------------------------------------- #
# Fixture expectations
# --------------------------------------------------------------------------- #
EXPECTED = {
    "continue.jsonl": (Verdict.OK, "continue approval path is legal"),
    "explicit-resume.jsonl": (Verdict.OK, "explicit resume approval path is legal"),
    "bare-auto-resume.jsonl": (Verdict.OK, "bare auto-resume approval path is legal"),
    "alternate-tool-name.jsonl": (
        Verdict.OK,
        "alternate builder-dispatch tool name is recognized",
    ),
    "multi-builder.jsonl": (
        Verdict.OK,
        "multiple correlated builders after one grant are legal",
    ),
    "approval-denied-then-granted.jsonl": (
        Verdict.OK,
        "a pending approval followed by a grant before dispatch is legal",
    ),
    "no-approval.jsonl": (
        Verdict.VIOLATION,
        "builder dispatch with no gate approval at all",
    ),
    "later-operator-approval.jsonl": (
        Verdict.VIOLATION,
        "approval arriving after builder dispatch cannot legalize it",
    ),
    "malformed-state.jsonl": (Verdict.MALFORMED, "non-increasing seq"),
    "unrecognized-type.jsonl": (Verdict.MALFORMED, "unrecognized event type"),
    "bad-schema.jsonl": (Verdict.MALFORMED, "payload schema violation"),
}


def read_fixture(path: Path) -> list:
    events = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path.name}:{lineno}: invalid JSON line: {exc}") from exc
    return events


def check_fixture_set() -> list:
    """Ensure every .jsonl in the dir is expected and vice versa; return errors."""
    errors = []
    present = {p.name for p in FIXTURES_DIR.glob("*.jsonl")}
    for name in present - set(EXPECTED):
        errors.append(f"unexpected fixture file not covered by EXPECTED: {name}")
    for name in set(EXPECTED) - present:
        errors.append(f"expected fixture missing from disk: {name}")
    return errors


def replay_single(name: str, verbose: bool) -> tuple:
    path = FIXTURES_DIR / name
    events = read_fixture(path)
    result = Replayer().replay(events)
    if verbose:
        for note in result.notes:
            print(f"    {note}")
        for violation in result.violations:
            print(f"    ! {violation}")
    return result


def main(argv: list) -> int:
    print("ed3d-orchestrate event replay (protocol-only seam, stdlib, deterministic)")

    # --- bounded fixture-set integrity --------------------------------------
    set_errors = check_fixture_set()
    if set_errors:
        for err in set_errors:
            print(f"FAIL fixture-set integrity: {err}")
        print(f"0/{len(EXPECTED)} event-replay fixtures passed")
        return 1

    # --- single-fixture detail mode -----------------------------------------
    if len(argv) > 1:
        target = argv[1]
        name = Path(target).name
        if not (FIXTURES_DIR / name).exists():
            print(f"FAIL: unknown fixture {target!r}")
            return 1
        expected, desc = EXPECTED[name]
        result = replay_single(name, verbose=True)
        status = "PASS" if result.verdict == expected else "FAIL"
        print(f"{status} {name}: expected={expected.value} got={result.verdict.value}")
        print(f"      reason: {result.reason}")
        print(f"      ({desc})")
        return 0 if result.verdict == expected else 1

    # --- full-suite mode ----------------------------------------------------
    failures = []
    for name, (expected, desc) in sorted(EXPECTED.items()):
        try:
            result = replay_single(name, verbose=False)
        except Exception as exc:  # file/JSON loading failure
            failures.append((name, f"load error: {exc}"))
            print(f"FAIL {name}: load error: {exc}")
            continue
        ok = result.verdict == expected
        if not ok:
            failures.append((name, result.reason))
        mark = "PASS" if ok else "FAIL"
        print(
            f"{mark:4} {name:34} expected={expected.value:9} got={result.verdict.value:9}"
            f"  {result.reason}"
        )
    print(f"{len(EXPECTED) - len(failures)}/{len(EXPECTED)} event-replay fixtures passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
