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
from copy import deepcopy
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
    "orchestration.ownership": (
        {
            "status": str,
            "sessionId": str,
            "transferFrom": str,
            "task": str,
            "planPath": str,
            "phase": str,
        },
        {
            "status": {"unowned", "owned", "transfer_pending", "recovery_required"},
            "phase": {"research", "execute", "review"},
        },
    ),
    "orchestration.resume": (
        {
            "sessionId": str,
            "task": str,
            "planPath": str,
            "phase": str,
            "ownershipStatus": str,
            "recordedOwner": str,
            "transferFrom": str,
            "explicit": bool,
            "taskMatches": bool,
            "planMatches": bool,
            "reviewActive": bool,
            "reviewVerdict": str,
            "approval": str,
            "preserveRequirements": bool,
        },
        {
            "phase": {"execute", "review"},
            "ownershipStatus": {"unowned", "owned", "transfer_pending", "recovery_required"},
            "approval": {"pending", "granted"},
        },
    ),
    "review.reconciliation": (
        {
            "status": str,
            "attempts": int,
            "round": int,
            "marker": str,
            "active": bool,
            "verdict": str,
        },
        {
            "status": {"none", "reconciliation_retrying", "reconciliation_exhausted"},
            "verdict": {"PENDING", "SHIP", "FIX-FIRST"},
        },
    ),
    "review.provenance": (
        {
            "round": int,
            "dispatchToolCallId": str,
            "reviewerAgentId": str,
        },
        {},
    ),
    "skill.invoked": ({"skill": str}, {}),
    "permission.requested": ({"toolCallId": str}, {}),
    "permission.completed": ({"toolCallId": str}, {}),
    "hook.start": ({"hook": str}, {}),
    "hook.end": ({"hook": str}, {}),
}

_OPTIONAL_SNAPSHOT_EVENTS = {
    "orchestration.ownership",
    "orchestration.resume",
    "review.reconciliation",
}


def _validate_snapshot(snapshot):
    if not isinstance(snapshot, dict):
        return "state snapshot must be an object"
    if set(snapshot) != {"approval", "review"}:
        return "state snapshot must contain exactly approval and review"
    if snapshot["approval"] not in {"pending", "granted", "denied"}:
        return "state snapshot approval is invalid"
    review = snapshot["review"]
    if not isinstance(review, dict):
        return "state snapshot review must be an object"
    required = {
        "active",
        "verdict",
        "round",
        "nonce",
        "history",
        "baseSha",
        "headSha",
        "recovery",
    }
    if set(review) != required:
        return "state snapshot review fields are incomplete"
    if not isinstance(review["active"], bool):
        return "state snapshot review.active must be a boolean"
    if not isinstance(review["verdict"], str):
        return "state snapshot review.verdict must be a string"
    if isinstance(review["round"], bool) or not isinstance(review["round"], int):
        return "state snapshot review.round must be an integer"
    if not isinstance(review["nonce"], str):
        return "state snapshot review.nonce must be a string"
    if not isinstance(review["history"], list):
        return "state snapshot review.history must be a list"
    if not isinstance(review["baseSha"], str) or not isinstance(review["headSha"], str):
        return "state snapshot review SHAs must be strings"
    recovery = review["recovery"]
    if not isinstance(recovery, dict) or set(recovery) != {"status", "attempts", "marker"}:
        return "state snapshot review.recovery is incomplete"
    if not isinstance(recovery["status"], str):
        return "state snapshot recovery.status must be a string"
    if isinstance(recovery["attempts"], bool) or not isinstance(recovery["attempts"], int):
        return "state snapshot recovery.attempts must be an integer"
    if recovery["marker"] is not None and not isinstance(recovery["marker"], str):
        return "state snapshot recovery.marker must be null or a string"
    return None


def _snapshot_from_payload(payload):
    snapshot = payload.get("snapshot")
    return deepcopy(snapshot) if isinstance(snapshot, dict) else None


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
    optional = {"snapshot": dict} if etype in _OPTIONAL_SNAPSHOT_EVENTS else {}
    missing = set(required) - set(payload)
    extra = set(payload) - set(required) - set(optional)
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
    for key, typ in optional.items():
        if key in payload and not isinstance(payload[key], typ):
            return f"payload.{key} must be an object, got {type(payload[key]).__name__}"
    for key, allowed in enums.items():
        if payload[key] not in allowed:
            return (
                f"payload.{key} must be one of {sorted(allowed)}, "
                f"got {payload[key]!r}"
            )
    if etype == "orchestration.ownership":
        if not payload["task"].strip() or not payload["planPath"].startswith("/"):
            return "persisted ownership must bind a non-empty task and absolute plan"
        if payload["status"] in {"owned", "transfer_pending"} and not payload["sessionId"].strip():
            return "persisted owned state requires a non-empty live session identity"
        if payload["status"] == "transfer_pending" and (
            not payload["transferFrom"].strip()
            or payload["transferFrom"] != payload["sessionId"]
        ):
            return "transfer_pending must retain the recorded owner in transferFrom"
        if payload["status"] == "unowned" and (
            payload["sessionId"] or payload["transferFrom"]
        ):
            return "unowned state cannot carry an owner identity"
    elif etype == "orchestration.resume":
        if (
            not payload["sessionId"].strip()
            or not payload["task"].strip()
            or not payload["planPath"].startswith("/")
        ):
            return "resume requires non-empty identity/task and absolute plan"
    elif etype == "orchestration.auto_resume":
        if not payload["task"].strip():
            return "auto-resume requires a non-empty task"
    elif etype == "review.reconciliation" and payload["round"] < 1:
        return "reconciliation round must be positive"
    elif etype == "review.provenance":
        if payload["round"] < 1:
            return "provenance round must be positive"
        if not payload["dispatchToolCallId"].strip() or not payload["reviewerAgentId"].strip():
            return "provenance requires non-empty dispatch and reviewer identities"
    if "snapshot" in payload:
        snapshot_error = _validate_snapshot(payload["snapshot"])
        if snapshot_error:
            return snapshot_error
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
    ownership: str = "unowned"
    owner_session: str = ""
    transfer_from: str = ""
    recovery_status: str = "none"
    recovery_attempts: int = 0
    preserved_requirements: bool = True
    review_active: bool = False
    review_verdict: str = "PENDING"
    review_round: int = 1
    review_nonce: str = ""
    review_history: list = field(default_factory=list)
    base_sha: str = ""
    head_sha: str = ""
    task: str | None = None
    plan_path: str = ""
    phase: str = ""
    provenance_round: int | None = None
    dispatch_tool_call_id: str = ""
    reviewer_agent_id: str = ""


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
        self.ownership = "unowned"
        self.owner_session = ""
        self.transfer_from = ""
        self.recovery_status = "none"
        self.recovery_attempts = 0
        self.preserved_requirements = True
        self.phase = ""
        self.review_active = False
        self.review_verdict = "PENDING"
        self.review_round = 1
        self.review_nonce = ""
        self.review_history = []
        self.base_sha = ""
        self.head_sha = ""
        self.provenance_round = None
        self.dispatch_tool_call_id = ""
        self.reviewer_agent_id = ""
        self.provenance_retry_consumed = False
        self.state_bound = False
        self.rearm_authorized = False
        self._builders = {}  # toolCallId -> task number (dispatched, uncorrelated yet)
        self._started = set()  # toolCallIds with a subagent.started

    def _state_snapshot(self):
        return {
            "approval": self.gate,
            "review": {
                "active": self.review_active,
                "verdict": self.review_verdict,
                "round": self.review_round,
                "nonce": self.review_nonce,
                "history": deepcopy(self.review_history),
                "baseSha": self.base_sha,
                "headSha": self.head_sha,
                "recovery": {
                    "status": self.recovery_status,
                    "attempts": self.recovery_attempts,
                    "marker": (
                        "review-reconciliation-unavailable"
                        if self.recovery_status in {
                            "reconciliation_retrying",
                            "reconciliation_exhausted",
                        }
                        else None
                    ),
                },
            },
        }

    def _snapshot_matches(self, snapshot):
        return snapshot is None or snapshot == self._state_snapshot()

    def _apply_snapshot(self, snapshot):
        if snapshot is None:
            return
        review = snapshot["review"]
        self.gate = snapshot["approval"]
        self.review_active = review["active"]
        self.review_verdict = review["verdict"]
        self.review_round = review["round"]
        self.review_nonce = review["nonce"]
        self.review_history = deepcopy(review["history"])
        self.base_sha = review["baseSha"]
        self.head_sha = review["headSha"]
        self.provenance_retry_consumed = False
        recovery = review["recovery"]
        self.recovery_status = recovery["status"]
        self.recovery_attempts = recovery["attempts"]

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
                result.ownership = self.ownership
                result.owner_session = self.owner_session
                result.transfer_from = self.transfer_from
                result.recovery_status = self.recovery_status
                result.recovery_attempts = self.recovery_attempts
                result.review_active = self.review_active
                result.review_verdict = self.review_verdict
                result.review_round = self.review_round
                result.review_nonce = self.review_nonce
                result.review_history = deepcopy(self.review_history)
                result.base_sha = self.base_sha
                result.head_sha = self.head_sha
                result.task = self.task
                result.plan_path = self.plan_path
                result.phase = self.phase
                result.provenance_round = self.provenance_round
                result.dispatch_tool_call_id = self.dispatch_tool_call_id
                result.reviewer_agent_id = self.reviewer_agent_id
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
                self.provenance_round = None
                self.dispatch_tool_call_id = ""
                self.reviewer_agent_id = ""
                self.provenance_retry_consumed = False
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
                self.ownership = "unowned"
                self.owner_session = ""
                self.transfer_from = ""
                self.recovery_status = "none"
                self.recovery_attempts = 0
                self.rearm_authorized = False
                self.phase = payload["phase"]
                self.review_active = False
                self.review_verdict = "PENDING"
                self.review_round = 1
                self.review_nonce = ""
                self.review_history = []
                self.base_sha = ""
                self.head_sha = ""
                self.provenance_round = None
                self.dispatch_tool_call_id = ""
                self.reviewer_agent_id = ""
                self.provenance_retry_consumed = False
                self.state_bound = False
                result.notes.append(
                    f"seq {event['seq']}: task start reset control-plane state "
                    f"for {self.task!r}"
                )
            elif etype == "orchestration.auto_resume":
                # Auto-resume is an observation of an existing binding, not a
                # replacement for the persisted task/plan/phase/review state.
                # A task_start may leave only the initial research phase
                # unbound; it still records the task and therefore locks it.
                task_matches = (
                    self.task is None or payload["task"] == self.task
                )
                plan_matches = (
                    not self.plan_path or payload["planPath"] == self.plan_path
                )
                phase_matches = (
                    not self.phase
                    or payload["phase"] == self.phase
                    or (not self.state_bound and self.phase == "research")
                )
                review_matches = (
                    not self.state_bound
                    or (
                        payload["reviewActive"] == self.review_active
                        and payload["reviewVerdict"] == self.review_verdict
                    )
                )
                claims_match = payload["taskMatches"] == task_matches
                valid_shape = (
                    bool(payload["planPath"])
                    and payload["planPath"].startswith("/")
                    and payload["planExists"]
                    and task_matches
                    and plan_matches
                    and phase_matches
                    and review_matches
                    and claims_match
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
                if not valid_shape:
                    self.unresolved_binding = True
                    if not claims_match and self.task is not None:
                        result.violations.append(
                            f"seq {event['seq']}: auto-resume taskMatches does not "
                            "match the persisted task"
                        )
                    if not (
                        task_matches
                        and plan_matches
                        and phase_matches
                        and review_matches
                    ):
                        result.violations.append(
                            f"seq {event['seq']}: auto-resume attempted to replace "
                            "the persisted task/plan/phase/review binding"
                        )
                    result.notes.append(
                        f"seq {event['seq']}: auto-resume refused; "
                        "state is not a validated in-progress loop"
                    )
                else:
                    self.gate = "pending"
                    self.grant_turn = None
                    self.grant_pre_turn = False
                    self.task = payload["task"]
                    self.plan_path = payload["planPath"]
                    self.phase = payload["phase"]
                    self.review_active = payload["reviewActive"]
                    self.review_verdict = payload["reviewVerdict"]
                    self.state_bound = True
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
            elif etype == "orchestration.ownership":
                snapshot = _snapshot_from_payload(payload)
                initial_observation_valid = (
                    not self.state_bound
                    and (self.task is None or payload["task"] == self.task)
                    and (not self.plan_path or payload["planPath"] == self.plan_path)
                    and (not self.phase or payload["phase"] == self.phase)
                )
                ownership_transition_valid = initial_observation_valid or (
                    payload["status"] == self.ownership
                    and payload["sessionId"] == self.owner_session
                    and payload["transferFrom"] == self.transfer_from
                    and payload["task"] == self.task
                    and payload["planPath"] == self.plan_path
                    and payload["phase"] == self.phase
                ) or (
                    self.ownership == "owned"
                    and payload["status"] == "transfer_pending"
                    and payload["sessionId"] == self.owner_session
                    and payload["transferFrom"] == self.owner_session
                    and payload["task"] == self.task
                    and payload["planPath"] == self.plan_path
                    and payload["phase"] == self.phase
                )
                if not ownership_transition_valid:
                    result.violations.append(
                        f"seq {event['seq']}: ownership transition does not "
                        "match the persisted task/plan/phase state or authorized transfer"
                    )
                    continue
                if self.state_bound and not self._snapshot_matches(snapshot):
                    result.violations.append(
                        f"seq {event['seq']}: ownership transition changed "
                        "the persisted approval/review nonce/history/SHA snapshot"
                    )
                    continue
                if payload["status"] == "recovery_required" and (
                    payload["sessionId"] or payload["transferFrom"]
                ):
                    result.violations.append(
                        f"seq {event['seq']}: recovery_required state cannot "
                        "claim a live owner"
                    )
                    continue
                self.ownership = payload["status"]
                self.owner_session = payload["sessionId"]
                self.transfer_from = payload["transferFrom"]
                self.task = payload["task"]
                self.plan_path = payload["planPath"]
                self.phase = payload["phase"]
                if not self.state_bound:
                    self.review_active = payload["phase"] == "review"
                    self.review_verdict = "PENDING"
                    self.review_round = 1
                    self.gate = "pending"
                    self.recovery_status = "none"
                    self.recovery_attempts = 0
                    self.rearm_authorized = False
                    self.review_nonce = ""
                    self.review_history = []
                    self.base_sha = ""
                    self.head_sha = ""
                    self._apply_snapshot(snapshot)
                self.state_bound = True
                result.notes.append(
                    f"seq {event['seq']}: ownership state {self.ownership!r} "
                    f"for {self.owner_session or 'no session'}"
                )
            elif etype == "orchestration.resume":
                snapshot = _snapshot_from_payload(payload)
                actual_task_match = self.task is None or payload["task"] == self.task
                actual_plan_match = self.plan_path == "" or payload["planPath"] == self.plan_path
                actual_phase_match = self.phase == "" or payload["phase"] == self.phase
                claimed_state_matches = (
                    payload["ownershipStatus"] == self.ownership
                    and payload["recordedOwner"] == self.owner_session
                    and payload["transferFrom"] == self.transfer_from
                )
                claimed_review_matches = (
                    not self.state_bound
                    or (
                        payload["reviewActive"] == self.review_active
                        and payload["reviewVerdict"] == self.review_verdict
                    )
                )
                claimed_snapshot_matches = self._snapshot_matches(snapshot)
                valid_binding = (
                    payload["explicit"]
                    and payload["sessionId"].strip()
                    and payload["planPath"].startswith("/")
                    and actual_task_match
                    and actual_plan_match
                    and actual_phase_match
                    and payload["taskMatches"] == actual_task_match
                    and payload["planMatches"] == actual_plan_match
                    and claimed_state_matches
                    and claimed_review_matches
                    and claimed_snapshot_matches
                    and payload["preserveRequirements"]
                    and payload["approval"] == self.gate
                )
                if not valid_binding:
                    result.violations.append(
                        f"seq {event['seq']}: resume refused because persisted "
                        "task/plan/phase/owner/review binding is invalid"
                    )
                elif self.ownership == "owned" and payload["sessionId"] == self.owner_session:
                    if (
                        self.recovery_status == "reconciliation_exhausted"
                        and payload["reviewActive"] is False
                        and payload["reviewVerdict"] == "PENDING"
                    ):
                        self.rearm_authorized = True
                        self.recovery_status = "none"
                        self.recovery_attempts = 0
                        self.provenance_retry_consumed = False
                    result.notes.append(
                        f"seq {event['seq']}: same-owner continuation preserved "
                        "approval and review requirements"
                    )
                elif (
                    self.ownership == "transfer_pending"
                    and payload["sessionId"] != self.owner_session
                    and payload["transferFrom"] == self.owner_session
                    and payload["transferFrom"] == self.transfer_from
                ):
                    self.owner_session = payload["sessionId"]
                    self.transfer_from = ""
                    self.ownership = "owned"
                    result.notes.append(
                        f"seq {event['seq']}: authorized ownership transfer claimed "
                        f"by {self.owner_session}"
                    )
                elif self.ownership in {"unowned", "recovery_required"} and payload["sessionId"]:
                    self.owner_session = payload["sessionId"]
                    self.transfer_from = ""
                    self.ownership = "owned"
                    result.notes.append(
                        f"seq {event['seq']}: explicit legacy recovery rebound "
                        f"ownership to {self.owner_session}"
                    )
                else:
                    result.violations.append(
                        f"seq {event['seq']}: unauthorized non-transfer resume "
                        "cannot inherit ownership"
                    )
                if valid_binding:
                    self.preserved_requirements = payload["preserveRequirements"]
                if payload["approval"] != "pending" or not payload["preserveRequirements"]:
                    result.violations.append(
                        f"seq {event['seq']}: resume did not preserve pending "
                        "approval/review requirements"
                    )
            elif etype == "review.provenance":
                same_round = payload["round"] == self.review_round
                if not same_round:
                    result.violations.append(
                        f"seq {event['seq']}: provenance must stay in the "
                        "same review round"
                    )
                elif not self.dispatch_tool_call_id:
                    self.provenance_round = payload["round"]
                    self.dispatch_tool_call_id = payload["dispatchToolCallId"]
                    self.reviewer_agent_id = payload["reviewerAgentId"]
                    self.provenance_retry_consumed = False
                    result.notes.append(
                        f"seq {event['seq']}: recorded initial dispatch/reviewer "
                        "provenance"
                    )
                elif self.recovery_status != "reconciliation_retrying":
                    if (
                        payload["dispatchToolCallId"] != self.dispatch_tool_call_id
                        or payload["reviewerAgentId"] != self.reviewer_agent_id
                    ):
                        result.violations.append(
                            f"seq {event['seq']}: new provenance requires the "
                            "authorized same-round retry transition"
                        )
                elif (
                    payload["dispatchToolCallId"] == self.dispatch_tool_call_id
                    and payload["reviewerAgentId"] == self.reviewer_agent_id
                ):
                    if self.provenance_retry_consumed:
                        result.notes.append(
                            f"seq {event['seq']}: observed already accepted "
                            "same-round retry provenance idempotently"
                        )
                    else:
                        result.violations.append(
                            f"seq {event['seq']}: same-round retry must replace "
                            "both failed dispatch and reviewer provenance"
                        )
                elif (
                    payload["dispatchToolCallId"] == self.dispatch_tool_call_id
                    or payload["reviewerAgentId"] == self.reviewer_agent_id
                ):
                    result.violations.append(
                        f"seq {event['seq']}: same-round retry must replace both "
                        "failed dispatch and reviewer provenance"
                    )
                elif self.provenance_retry_consumed:
                    result.violations.append(
                        f"seq {event['seq']}: same-round retry provenance "
                        "replacement authorization was already consumed"
                    )
                else:
                    self.provenance_round = payload["round"]
                    self.dispatch_tool_call_id = payload["dispatchToolCallId"]
                    self.reviewer_agent_id = payload["reviewerAgentId"]
                    self.provenance_retry_consumed = True
                    result.notes.append(
                        f"seq {event['seq']}: replaced failed dispatch/reviewer "
                        "provenance for the bounded retry"
                    )
            elif etype == "review.reconciliation":
                snapshot = _snapshot_from_payload(payload)
                transition_valid = True
                if not self._snapshot_matches(snapshot):
                    transition_valid = False
                    result.violations.append(
                        f"seq {event['seq']}: reconciliation changed the "
                        "persisted approval/review nonce/history/SHA snapshot"
                    )
                valid_shape = (
                    payload["attempts"] in {0, 1}
                    and payload["round"] == self.review_round
                    and payload["verdict"] == "PENDING"
                )
                if not valid_shape:
                    transition_valid = False
                    result.violations.append(
                        f"seq {event['seq']}: reconciliation metadata does not "
                        "match the persisted current-round PENDING review"
                    )
                if payload["status"] == "reconciliation_retrying":
                    if (
                        payload["attempts"] != 1
                        or payload["marker"] != "review-reconciliation-unavailable"
                        or not payload["active"]
                        or self.recovery_status == "reconciliation_retrying"
                        or (
                            self.recovery_status == "reconciliation_exhausted"
                            and not self.rearm_authorized
                        )
                    ):
                        transition_valid = False
                        result.violations.append(
                            f"seq {event['seq']}: reconciliation retry is repeated "
                            "or not authorized by the persisted recovery state"
                        )
                elif payload["status"] == "reconciliation_exhausted":
                    if (
                        payload["attempts"] != 1
                        or payload["marker"] != "review-reconciliation-unavailable"
                        or payload["active"]
                        or payload["verdict"] != "PENDING"
                        or self.recovery_status != "reconciliation_retrying"
                    ):
                        transition_valid = False
                        result.violations.append(
                            f"seq {event['seq']}: exhausted recovery must be the "
                            "inactive no-verdict transition after one retry"
                        )
                elif payload["status"] == "none":
                    if (
                        self.recovery_status in {
                            "reconciliation_retrying",
                            "reconciliation_exhausted",
                        }
                        and not self.rearm_authorized
                    ) or (
                        payload["attempts"] != 0
                        or payload["marker"] not in {"", None}
                    ) or (
                        payload["verdict"] != "PENDING"
                    ):
                        transition_valid = False
                        result.violations.append(
                            f"seq {event['seq']}: recovery state cannot mutate "
                            "into a verdict without authorized re-arm"
                        )
                    if self.review_active and not payload["active"]:
                        transition_valid = False
                        result.violations.append(
                            f"seq {event['seq']}: reconciliation cannot deactivate "
                            "an active pending review without a verdict or "
                            "explicit exhausted recovery"
                        )
                if transition_valid:
                    self.recovery_status = payload["status"]
                    self.recovery_attempts = payload["attempts"]
                    self.review_active = payload["active"]
                    self.review_verdict = payload["verdict"]
                    self.rearm_authorized = False
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
        result.ownership = self.ownership
        result.owner_session = self.owner_session
        result.transfer_from = self.transfer_from
        result.recovery_status = self.recovery_status
        result.recovery_attempts = self.recovery_attempts
        result.preserved_requirements = self.preserved_requirements
        result.review_active = self.review_active
        result.review_verdict = self.review_verdict
        result.review_round = self.review_round
        result.review_nonce = self.review_nonce
        result.review_history = deepcopy(self.review_history)
        result.base_sha = self.base_sha
        result.head_sha = self.head_sha
        result.task = self.task
        result.plan_path = self.plan_path
        result.phase = self.phase
        result.provenance_round = self.provenance_round
        result.dispatch_tool_call_id = self.dispatch_tool_call_id
        result.reviewer_agent_id = self.reviewer_agent_id

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
    "same-owner-continuation.jsonl": (
        Verdict.OK,
        "same-owner resume preserves approval and active review requirements",
    ),
    "authorized-transfer.jsonl": (
        Verdict.VIOLATION,
        "a transfer claim preserves review requirements but builder dispatch still needs approval",
    ),
    "unauthorized-transfer.jsonl": (
        Verdict.VIOLATION,
        "a non-transfer session cannot inherit ownership",
    ),
    "transfer-without-claim.jsonl": (
        Verdict.VIOLATION,
        "transfer-pending state cannot dispatch before a claim",
    ),
    "legacy-recovery.jsonl": (
        Verdict.OK,
        "explicit identity-bearing resume rebinds legacy ownership without a verdict",
    ),
    "reconciliation-exhausted-rearm.jsonl": (
        Verdict.OK,
        "unavailable reconciliation exhausts once and later re-arms explicitly",
    ),
    "mismatched-binding.jsonl": (
        Verdict.VIOLATION,
        "resume task identity must match the persisted task and plan binding",
    ),
    "empty-identity.jsonl": (
        Verdict.MALFORMED,
        "persisted owned state cannot have an empty live session identity",
    ),
    "unauthorized-exhaustion-rearm.jsonl": (
        Verdict.VIOLATION,
        "only the recorded owner may re-arm exhausted reconciliation",
    ),
    "repeated-reconciliation-retry.jsonl": (
        Verdict.VIOLATION,
        "one reconciliation retry cannot be repeated without an authorized re-arm",
    ),
    "verdict-mutation-after-exhaustion.jsonl": (
        Verdict.VIOLATION,
        "exhausted recovery cannot be mutated into a verdict",
    ),
    "exhausted-transfer-retry.jsonl": (
        Verdict.VIOLATION,
        "ownership transfer cannot reset an exhausted retry budget",
    ),
    "ownership-observation-retry.jsonl": (
        Verdict.VIOLATION,
        "repeated ownership observations cannot reset a consumed retry budget",
    ),
    "retry-reset-retry.jsonl": (
        Verdict.VIOLATION,
        "an unauthorized none transition cannot reset and reuse the retry budget",
    ),
    "fresh-task-resets-owner-review.jsonl": (
        Verdict.OK,
        "a fresh task clears prior ownership, review, and recovery state",
    ),
    "snapshot-preserving-transfer.jsonl": (
        Verdict.OK,
        "authorized transfer carries the actual approval, review, nonce, history, and SHA snapshot",
    ),
    "snapshot-mutation-transfer.jsonl": (
        Verdict.VIOLATION,
        "ownership cannot mutate the carried approval, review, nonce, history, or SHA snapshot",
    ),
    "reconciliation-deactivation-without-verdict.jsonl": (
        Verdict.VIOLATION,
        "an active pending review cannot be deactivated without a verdict or exhaustion",
    ),
    "auto-resume-binding-overwrite.jsonl": (
        Verdict.VIOLATION,
        "auto-resume cannot replace a persisted plan or review binding",
    ),
    "task-start-binding-overwrite.jsonl": (
        Verdict.VIOLATION,
        "ownership observation cannot replace the task recorded by task_start",
    ),
    "same-round-retry-provenance-success.jsonl": (
        Verdict.OK,
        "a same-round retry replaces failed dispatch and reviewer provenance",
    ),
    "same-round-retry-provenance-rejected.jsonl": (
        Verdict.VIOLATION,
        "a cross-round retry provenance observation is rejected",
    ),
    "same-round-retry-provenance-exhausted.jsonl": (
        Verdict.OK,
        "retry exhaustion preserves the failed provenance and no-verdict state",
    ),
    "same-round-retry-provenance-partial-dispatch.jsonl": (
        Verdict.VIOLATION,
        "a retry retaining the failed dispatch identity is rejected",
    ),
    "same-round-retry-provenance-partial-reviewer.jsonl": (
        Verdict.VIOLATION,
        "a retry retaining the failed reviewer identity is rejected",
    ),
    "same-round-retry-provenance-repeated.jsonl": (
        Verdict.VIOLATION,
        "a same-round provenance replacement is single-use with idempotent repeats",
    ),
    "same-round-retry-provenance-new-round.jsonl": (
        Verdict.OK,
        "a new review round receives a fresh provenance replacement authorization",
    ),
    "same-round-retry-provenance-rearm.jsonl": (
        Verdict.OK,
        "an authorized exhausted-recovery re-arm permits one fresh replacement",
    ),
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
    if name == "same-owner-continuation.jsonl":
        if result.ownership != "owned" or not result.preserved_requirements:
            return "same-owner continuation did not preserve owner/review requirements"
    if name == "authorized-transfer.jsonl":
        if result.owner_session != "owner-b":
            return "authorized transfer did not claim the new owner"
    if name == "unauthorized-transfer.jsonl":
        if result.ownership != "owned" or result.owner_session != "owner-a":
            return "unauthorized session mutated ownership"
    if name == "transfer-without-claim.jsonl":
        if result.ownership != "transfer_pending":
            return "transfer-pending state did not remain unclaimed"
    if name == "legacy-recovery.jsonl":
        if result.ownership != "owned" or result.owner_session != "owner-new":
            return "legacy recovery did not bind the explicit session"
    if name == "reconciliation-exhausted-rearm.jsonl":
        if result.recovery_attempts != 1 or result.recovery_status != "reconciliation_retrying":
            return "reconciliation recovery was not bounded and explicitly re-armed"
    if name == "mismatched-binding.jsonl":
        if not any("persisted task/plan/phase" in violation for violation in result.violations):
            return "mismatched binding did not compare against persisted identity"
    if name == "unauthorized-exhaustion-rearm.jsonl":
        if result.recovery_status != "reconciliation_exhausted" or result.recovery_attempts != 1:
            return "unauthorized re-arm changed persisted exhausted recovery"
    if name == "repeated-reconciliation-retry.jsonl":
        if result.recovery_status != "reconciliation_retrying" or result.recovery_attempts != 1:
            return "repeated retry changed the already-consumed retry state"
    if name == "verdict-mutation-after-exhaustion.jsonl":
        if result.recovery_status != "reconciliation_exhausted" or result.review_verdict != "PENDING":
            return "verdict mutation changed the persisted exhausted state"
    if name == "exhausted-transfer-retry.jsonl":
        if result.recovery_status != "reconciliation_exhausted" or result.recovery_attempts != 1:
            return "ownership transfer reset exhausted recovery or authorized a retry"
    if name == "ownership-observation-retry.jsonl":
        if not any("reconciliation retry is repeated" in violation for violation in result.violations):
            return "repeated ownership observation did not preserve the consumed retry budget"
    if name == "retry-reset-retry.jsonl":
        if not any("recovery state cannot mutate" in violation for violation in result.violations):
            return "none transition reset the consumed retry budget"
    if name == "fresh-task-resets-owner-review.jsonl":
        if (
            result.ownership != "unowned"
            or result.owner_session
            or result.transfer_from
            or result.review_active
            or result.review_verdict != "PENDING"
            or result.recovery_status != "none"
            or result.recovery_attempts != 0
        ):
            return "fresh task retained task-scoped owner, review, or recovery state"
    if name == "snapshot-preserving-transfer.jsonl":
        if (
            result.review_nonce != "abcdef12"
            or result.review_history != [
                {"round": 1, "verdict": "FIX-FIRST", "critical_high": 1, "advisory": 0}
            ]
            or result.base_sha != "base-sha"
            or result.head_sha != "head-sha"
            or result.gate != "pending"
            or not result.review_active
        ):
            return "transfer did not preserve the actual review snapshot"
    if name == "snapshot-mutation-transfer.jsonl":
        if not any("nonce/history/SHA snapshot" in violation for violation in result.violations):
            return "snapshot mutation was not rejected"
    if name == "reconciliation-deactivation-without-verdict.jsonl":
        if (
            not result.review_active
            or result.recovery_status != "none"
            or not any("deactivate" in violation for violation in result.violations)
        ):
            return "active pending review was deactivated without a permitted transition"
    if name == "auto-resume-binding-overwrite.jsonl":
        if (
            result.task != "review task"
            or result.plan_path != "/repo/plan.md"
            or result.phase != "execute"
            or result.review_active
            or result.review_verdict != "PENDING"
            or not any("persisted task/plan/phase/review" in violation for violation in result.violations)
        ):
            return "auto-resume binding overwrite was not rejected before mutation"
    if name == "task-start-binding-overwrite.jsonl":
        if (
            result.task != "recorded task"
            or result.plan_path
            or result.phase != "research"
            or result.ownership != "unowned"
            or not any("persisted task/plan/phase" in violation for violation in result.violations)
        ):
            return "task_start binding was overwritten by initial ownership observation"
    if name == "same-round-retry-provenance-success.jsonl":
        if (
            result.recovery_status != "reconciliation_retrying"
            or result.recovery_attempts != 1
            or result.review_round != 1
            or result.review_nonce != "a1b2c3d4"
            or result.review_history != [
                {"round": 1, "verdict": "FIX-FIRST", "critical_high": 1, "advisory": 0}
            ]
            or result.base_sha != "base-sha"
            or result.head_sha != "head-sha"
            or result.gate != "pending"
            or result.ownership != "owned"
            or result.owner_session != "owner-a"
            or result.dispatch_tool_call_id != "call-retry"
            or result.reviewer_agent_id != "agent-retry"
            or not any("replaced" in note for note in result.notes)
        ):
            return "successful retry did not replace only the failed provenance"
    if name == "same-round-retry-provenance-rejected.jsonl":
        if (
            result.dispatch_tool_call_id != "call-failed"
            or result.reviewer_agent_id != "agent-failed"
            or not any("same review round" in violation for violation in result.violations)
        ):
            return "cross-round provenance rejection did not preserve failed identities"
    if name == "same-round-retry-provenance-exhausted.jsonl":
        if (
            result.recovery_status != "reconciliation_exhausted"
            or result.recovery_attempts != 1
            or result.review_active
            or result.review_verdict != "PENDING"
            or result.review_nonce != "a1b2c3d4"
            or result.review_history != [
                {"round": 1, "verdict": "FIX-FIRST", "critical_high": 1, "advisory": 0}
            ]
            or result.base_sha != "base-sha"
            or result.head_sha != "head-sha"
            or result.gate != "pending"
            or result.ownership != "owned"
            or result.owner_session != "owner-a"
            or result.dispatch_tool_call_id != "call-failed"
            or result.reviewer_agent_id != "agent-failed"
        ):
            return "exhaustion did not preserve bounded no-verdict state and provenance"
    if name in {
        "same-round-retry-provenance-partial-dispatch.jsonl",
        "same-round-retry-provenance-partial-reviewer.jsonl",
    }:
        if (
            result.recovery_status != "reconciliation_retrying"
            or result.recovery_attempts != 1
            or not result.review_active
            or result.review_verdict != "PENDING"
            or result.review_nonce != "a1b2c3d4"
            or result.review_history != [
                {"round": 1, "verdict": "FIX-FIRST", "critical_high": 1, "advisory": 0}
            ]
            or result.base_sha != "base-sha"
            or result.head_sha != "head-sha"
            or result.dispatch_tool_call_id != "call-failed"
            or result.reviewer_agent_id != "agent-failed"
            or not any("both" in violation for violation in result.violations)
        ):
            return "partial provenance replacement mutated accepted or protected state"
    if name == "same-round-retry-provenance-repeated.jsonl":
        if (
            result.recovery_status != "reconciliation_retrying"
            or result.recovery_attempts != 1
            or result.dispatch_tool_call_id != "call-retry"
            or result.reviewer_agent_id != "agent-retry"
            or len(result.violations) != 2
            or not any("already consumed" in violation for violation in result.violations)
        ):
            return "repeated provenance replacement was not single-use or idempotent"
    if name == "same-round-retry-provenance-new-round.jsonl":
        if (
            result.review_round != 2
            or result.provenance_round != 2
            or result.dispatch_tool_call_id != "call-round-2-retry"
            or result.reviewer_agent_id != "agent-round-2-retry"
            or result.recovery_status != "reconciliation_retrying"
        ):
            return "new review round did not receive fresh replacement authorization"
    if name == "same-round-retry-provenance-rearm.jsonl":
        if (
            result.recovery_status != "reconciliation_retrying"
            or result.recovery_attempts != 1
            or result.dispatch_tool_call_id != "call-retry"
            or result.reviewer_agent_id != "agent-retry"
            or result.recovery_status == "reconciliation_exhausted"
        ):
            return "authorized exhausted-recovery re-arm did not permit one replacement"
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
