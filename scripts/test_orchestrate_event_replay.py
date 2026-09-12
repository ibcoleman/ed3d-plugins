#!/usr/bin/env python3
"""Deterministic event replay tests for the ed3d-orchestrate approval gate.

Replays synthetic JSONL event streams through the plan-review -> approval ->
builder-dispatch protocol and verifies, purely at the protocol layer (a
protocol-only seam; no runtime enforcement is claimed), that:

  * every event is strictly schema-valid (exact payload key set, types, enums),
  * seq values are strictly increasing across the stream,
  * event types are recognized,
  * a persisted ``gate.approval == "granted"`` precedes every builder dispatch
    (``builder.task``) and every ``subagent.started``,
  * a grant only authorizes the turn (or pre-turn context) it was written in:
    a grant written before any ``assistant.turn_start`` cannot authorize a
    later turn,
  * builder dispatches correlate to their started/completed subagents by
    ``toolCallId``,
  * the builder-dispatch tool name is flexible (alternate tool names such as
    ``Task`` are accepted; the protocol seam is the event type, not the tool).

The ``type``/``payload`` shapes below are synthetic *seam* events: they are a
minimal, hand-authored vocabulary designed to exercise the protocol layer in
isolation. They are NOT raw Copilot CLI ``events.jsonl`` records, and this
replayer does NOT claim to accept raw ``events.jsonl`` as-is. Real Copilot
events must be adapted (mapped/reduced) onto this seam vocabulary before replay
— e.g. a permissions prompt is represented as a ``gate.approval`` and a subagent
dispatch as a ``builder.task``/``subagent.*`` pair keyed by ``toolCallId``.
Treat fixture verdicts as protocol-layer only, not as evidence that any
particular real event stream passes.

These are synthetic protocol tests: they establish the approval/reset seam
only and do not claim native mechanical enforcement of builder dispatch.

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
    "session.loop_reset": ({"loop": int}, {}),
    "orchestration.task_start": (
        {"task": str, "phase": str, "approval": str, "handoffStatus": str},
        {
            "phase": {"research"},
            "approval": {"pending"},
            "handoffStatus": {"not_started"},
        },
    ),
    "orchestration.auto_resume": (
        {
            "task": str,
            "planPath": str,
            "phase": str,
            "planExists": bool,
            "taskMatches": bool,
            "reviewActive": bool,
            "reviewVerdict": str,
        },
        {"phase": {"execute", "review"}},
    ),
    "orchestration.pending_reset": (
        {
            "requestedTask": str,
            "priorTask": str,
            "priorPlanPath": str,
            "resetPending": bool,
            "approval": str,
        },
        {"approval": {"pending"}},
    ),
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
        if typ is bool and not isinstance(val, bool):
            return f"payload.{key} must be a boolean, got {type(val).__name__}"
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
    unresolved_reset: bool = False
    unresolved_binding: bool = False


class Replayer:
    """Replays an event stream and records protocol verdicts at the seam."""

    def __init__(self):
        self.gate = "pending"  # persisted gate.approval
        self.path = ""
        self.turn = None  # current assistant turn number (None if none seen)
        self.grant_turn = None  # turn in which gate became granted (None if none)
        self.grant_pre_turn = False  # grant written before any assistant.turn_start
        self.task = None
        self.plan_path = ""
        self.unresolved_reset = False
        self.unresolved_binding = False
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
                result.gate = self.gate
                result.path = self.path
                result.unresolved_reset = self.unresolved_reset
                result.unresolved_binding = self.unresolved_binding
                return result
            prev_seq = event["seq"]
            result.events_processed = idx + 1
            etype, payload = event["type"], event["payload"]

            if etype == "gate.approval":
                self.gate = payload["approval"]
                self.path = payload["path"]
                if self.gate == "granted":
                    self.grant_turn = self.turn
                    self.grant_pre_turn = self.turn is None
                    context = (
                        "pre-turn (no assistant.turn_start yet)"
                        if self.turn is None
                        else f"turn {self.turn}"
                    )
                    result.notes.append(
                        f"seq {event['seq']}: gate.approval granted "
                        f"(path={self.path!r}, {context})"
                    )
                else:
                    self.grant_turn = None
                    self.grant_pre_turn = False
            elif etype == "builder.task":
                if self.gate != "granted":
                    result.violations.append(
                        f"seq {event['seq']}: builder.task (task {payload['task']}) "
                        f"dispatched while gate.approval={self.gate!r} (not granted)"
                    )
                elif self.unresolved_reset or self.unresolved_binding:
                    result.violations.append(
                        f"seq {event['seq']}: builder.task (task {payload['task']}) "
                        "dispatched before unresolved reset/task binding was "
                        "explicitly resolved"
                    )
                elif self.grant_turn is not None and self.turn != self.grant_turn:
                    result.violations.append(
                        f"seq {event['seq']}: builder.task (task {payload['task']}) "
                        f"dispatched in turn {self.turn} but grant was written in "
                        f"turn {self.grant_turn} (stale/immediacy)"
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
                elif self.unresolved_reset or self.unresolved_binding:
                    result.violations.append(
                        f"seq {event['seq']}: subagent.started "
                        f"({payload['agentName']}) dispatched before unresolved "
                        "reset/task binding was explicitly resolved"
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
            elif etype == "assistant.turn_start":
                new_turn = payload["turn"]
                # A grant only authorizes the turn it was written in. Two cases
                # make a grant stale when a new turn starts:
                #  * the grant was written pre-turn (before any turn marker):
                #    entering the first turn establishes turn context the grant
                #    was never part of, so it cannot authorize that turn;
                #  * the grant was written in an earlier, different turn.
                if self.gate == "granted" and self.grant_pre_turn:
                    self.gate = "pending"
                    self.grant_turn = None
                    self.grant_pre_turn = False
                    result.notes.append(
                        f"seq {event['seq']}: turn {new_turn} invalidated "
                        "pre-turn grant (no turn was active when written)"
                    )
                elif (
                    self.gate == "granted"
                    and self.grant_turn is not None
                    and self.turn is not None
                    and new_turn != self.turn
                ):
                    self.gate = "pending"
                    self.grant_turn = None
                    result.notes.append(
                        f"seq {event['seq']}: new turn {new_turn} invalidated "
                        f"grant from turn {self.turn}"
                    )
                self.turn = new_turn
            elif etype == "assistant.turn_end":
                # Ending the turn that wrote the grant makes it stale: any
                # dispatch in a later turn cannot be "immediately before dispatch".
                if (
                    self.gate == "granted"
                    and self.grant_turn is not None
                    and self.grant_turn == self.turn
                ):
                    self.gate = "pending"
                    self.grant_turn = None
                    result.notes.append(
                        f"seq {event['seq']}: turn {self.turn} ended; grant no "
                        "longer valid for dispatch"
                    )
            elif etype == "session.loop_reset":
                # A new orchestration loop begins with a clean gate: a grant
                # from a prior loop must not authorize a new loop's dispatch.
                self.gate = "pending"
                self.grant_turn = None
                self.grant_pre_turn = False
                self.unresolved_reset = False
                self.unresolved_binding = False
                result.notes.append(
                    f"seq {event['seq']}: new loop {payload['loop']} reset "
                    "gate to pending"
                )
            elif etype == "orchestration.task_start":
                self.task = payload["task"]
                self.path = ""
                self.plan_path = ""
                self.gate = "pending"
                self.grant_turn = None
                self.grant_pre_turn = False
                self.unresolved_reset = False
                self.unresolved_binding = False
                result.notes.append(
                    f"seq {event['seq']}: task start reset control-plane state "
                    f"for {self.task!r}"
                )
            elif etype == "orchestration.auto_resume":
                # Resuming never carries approval across the checkpoint.  A
                # valid binding clears only the binding rejection; a pending
                # reset remains unresolved until an explicit task reset.
                self.gate = "pending"
                self.grant_turn = None
                self.grant_pre_turn = False
                valid = (
                    bool(payload["planPath"])
                    and payload["planPath"].startswith("/")
                    and payload["planExists"]
                    and payload["taskMatches"]
                    and (
                        (
                            payload["phase"] == "execute"
                            and not payload["reviewActive"]
                            and payload["reviewVerdict"] == "PENDING"
                        )
                        or (
                            payload["phase"] == "review"
                            and payload["reviewActive"]
                            and payload["reviewVerdict"] in {"PENDING", "FIX-FIRST"}
                        )
                    )
                )
                self.task = payload["task"]
                self.plan_path = payload["planPath"]
                if not valid:
                    self.unresolved_binding = True
                    result.notes.append(
                        f"seq {event['seq']}: auto-resume refused; "
                        "state is not a validated in-progress loop"
                    )
                else:
                    self.unresolved_binding = False
                    result.notes.append(
                        f"seq {event['seq']}: validated auto-resume for "
                        f"{self.task!r}"
                    )
            elif etype == "orchestration.pending_reset":
                if payload["resetPending"]:
                    self.gate = "pending"
                    self.grant_turn = None
                    self.grant_pre_turn = False
                    self.unresolved_reset = True
                    result.notes.append(
                        f"seq {event['seq']}: pending reset handoff for "
                        f"{payload['requestedTask']!r}; execution remains refused"
                    )
            # All other recognized types are informational; no protocol effect.

        # Correlation completeness: any dispatched builder never started?
        for cid, task in self._builders.items():
            if cid not in self._started:
                result.notes.append(
                    f"builder.task {task} (toolCallId {cid}) has no matching "
                    "subagent.started (uncorrelated)"
                )

        # Reflect the final replayer state so result.gate/path report the
        # persisted gate/path instead of misleading defaults.
        result.gate = self.gate
        result.path = self.path
        result.unresolved_reset = self.unresolved_reset
        result.unresolved_binding = self.unresolved_binding

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
    "bare-auto-resume.jsonl": (
        Verdict.OK,
        "bare auto-resume re-presents a pending approval without dispatch",
    ),
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
        "denied followed by a later grant before dispatch is legal",
    ),
    "grant-then-denied-blocks-dispatch.jsonl": (
        Verdict.VIOLATION,
        "a grant revoked by a later denial cannot authorize a dispatch",
    ),
    "approval-denied-blocks-dispatch.jsonl": (
        Verdict.VIOLATION,
        "builder dispatch while gate.approval is denied",
    ),
    "stale-granted-new-loop.jsonl": (
        Verdict.VIOLATION,
        "a stale grant from a prior loop cannot authorize a new loop",
    ),
    "stale-granted-new-task.jsonl": (
        Verdict.VIOLATION,
        "a prior task grant is reset before a new task dispatch",
    ),
    "clean-default-no-auto-resume.jsonl": (
        Verdict.VIOLATION,
        "a clean default state cannot auto-resume a builder",
    ),
    "pending-reset.jsonl": (
        Verdict.VIOLATION,
        "a pending read-only reset handoff cannot authorize execution",
    ),
    "pending-reset-recovery.jsonl": (
        Verdict.OK,
        "an explicit new task reset resolves a pending reset before dispatch",
    ),
    "plan-bound-approval-resume.jsonl": (
        Verdict.OK,
        "a plan-bound execute checkpoint can resume before explicit approval",
    ),
    "active-pending-review-resume.jsonl": (
        Verdict.OK,
        "an active PENDING review can resume without requiring a terminal verdict",
    ),
    "task-binding-mismatch.jsonl": (
        Verdict.VIOLATION,
        "a mismatched task binding remains blocked after a later grant",
    ),
    "task-binding-recovery.jsonl": (
        Verdict.OK,
        "a valid binding explicitly resolves a prior resume rejection",
    ),
    "turn-grant-immediate.jsonl": (
        Verdict.OK,
        "grant written immediately before dispatch in the same turn is legal",
    ),
    "stale-grant-across-turn.jsonl": (
        Verdict.VIOLATION,
        "grant from an earlier turn cannot authorize a later operator turn",
    ),
    "pre-turn-grant-stale.jsonl": (
        Verdict.VIOLATION,
        "a grant written before any assistant turn marker cannot authorize "
        "a later turn",
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


def check_resume_semantics(name: str, result: ReplayResult) -> str | None:
    """Check the meaning of resume fixtures, not only their final verdict."""
    if name in {"plan-bound-approval-resume.jsonl",
                "active-pending-review-resume.jsonl",
                "task-binding-recovery.jsonl"}:
        if not any("validated auto-resume" in note for note in result.notes):
            return "expected a validated auto-resume note"
    if name == "task-binding-mismatch.jsonl":
        if not any("auto-resume refused" in note for note in result.notes):
            return "expected an auto-resume refusal note"
        if not result.unresolved_binding or not result.violations:
            return "expected unresolved binding to block dispatch"
    if name == "pending-reset.jsonl" and not result.violations:
        return "expected unresolved reset to block dispatch"
    if name == "pending-reset-recovery.jsonl":
        if result.unresolved_reset:
            return "explicit reset recovery should clear the pending reset"
    return None


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
        semantic_error = check_resume_semantics(name, result)
        status = (
            "PASS"
            if result.verdict == expected and semantic_error is None
            else "FAIL"
        )
        print(f"{status} {name}: expected={expected.value} got={result.verdict.value}")
        print(f"      reason: {result.reason}")
        if semantic_error:
            print(f"      semantic check: {semantic_error}")
        print(f"      ({desc})")
        return 0 if result.verdict == expected and semantic_error is None else 1

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
        semantic_error = check_resume_semantics(name, result)
        if semantic_error:
            ok = False
        if not ok:
            failures.append((name, semantic_error or result.reason))
        mark = "PASS" if ok else "FAIL"
        print(
            f"{mark:4} {name:34} expected={expected.value:9} got={result.verdict.value:9}"
            f"  {result.reason}"
        )
    print(f"{len(EXPECTED) - len(failures)}/{len(EXPECTED)} event-replay fixtures passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
