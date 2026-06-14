"""
services/audit_service.py — Rail-Flow AI

AuditService persists the result of a rescheduling run to:
  - rescheduling_runs     (one row per compute invocation)
  - rescheduling_actions  (one row per recommended action)
  - detected_conflicts    (one row per conflict found)

It is called at the end of Algorithm 2 (PersistAudit, line 19 of the
algorithm report).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from models import (
    db,
    ReschedulingRun,
    ReschedulingAction,
    DetectedConflict,
)


# ---------------------------------------------------------------------------
# Input data classes
# ---------------------------------------------------------------------------

@dataclass
class ActionRecord:
    """One recommended action to include in the audit."""
    action_sequence: int
    action_type: str          # e.g. "hold", "reorder", "cancel"
    run_id: Optional[str] = None
    station_code: Optional[str] = None
    connection_id: Optional[int] = None
    action_payload: dict = field(default_factory=dict)
    explanation: str = ""
    constraint_violated: Optional[str] = None


@dataclass
class ConflictRecord:
    """One detected conflict to include in the audit."""
    first_run_id: str
    second_run_id: str
    conflict_type: str        # e.g. "headway", "capacity", "direction"
    connection_id: Optional[int] = None
    conflict_start: Optional[datetime] = None
    conflict_end: Optional[datetime] = None
    resolved: bool = False
    resolution_action_sequence: Optional[int] = None


# ---------------------------------------------------------------------------
# AuditService
# ---------------------------------------------------------------------------

class AuditService:
    """
    Persist a complete rescheduling run result to the database.

    Usage::

        svc = AuditService()
        run = svc.persist_run(
            snapshot_id="...",
            policy_name="beam_search",
            predictor_name="historical_baseline_v1",
            horizon_minutes=60,
            commit_window_minutes=10,
            objective_before=180.0,
            objective_after=45.0,
            actions=[ActionRecord(...)],
            conflicts=[ConflictRecord(...)],
            compute_time_ms=237,
            status="success",
            configuration={"beam_width": 8},
        )
    """

    def persist_run(
        self,
        snapshot_id: str,
        policy_name: str,
        predictor_name: str,
        horizon_minutes: int,
        commit_window_minutes: int,
        objective_before: Optional[float],
        objective_after: Optional[float],
        actions: list[ActionRecord],
        conflicts: list[ConflictRecord],
        compute_time_ms: Optional[int] = None,
        status: str = "success",
        secondary_delay_before_seconds: Optional[int] = None,
        secondary_delay_after_seconds: Optional[int] = None,
        configuration: Optional[dict] = None,
    ) -> ReschedulingRun:
        """
        Write a :class:`ReschedulingRun` and its associated actions and
        conflicts to the database in a single transaction.

        :returns: The newly inserted :class:`ReschedulingRun` ORM row.
        """
        run = ReschedulingRun(
            snapshot_id=snapshot_id,
            status=status,
            policy_name=policy_name,
            predictor_name=predictor_name,
            horizon_minutes=horizon_minutes,
            commit_window_minutes=commit_window_minutes,
            objective_before=objective_before,
            objective_after=objective_after,
            secondary_delay_before_seconds=secondary_delay_before_seconds,
            secondary_delay_after_seconds=secondary_delay_after_seconds,
            compute_time_ms=compute_time_ms,
            configuration=configuration or {},
        )
        db.session.add(run)
        db.session.flush()   # populate run.rescheduling_run_id

        # Build a sequence -> action_id map for conflict resolution references
        seq_to_action: dict[int, ReschedulingAction] = {}

        for rec in sorted(actions, key=lambda a: a.action_sequence):
            action = ReschedulingAction(
                rescheduling_run_id=run.rescheduling_run_id,
                action_sequence=rec.action_sequence,
                action_type=rec.action_type,
                run_id=rec.run_id,
                station_code=rec.station_code,
                connection_id=rec.connection_id,
                action_payload=rec.action_payload,
                explanation=rec.explanation,
                constraint_violated=rec.constraint_violated,
            )
            db.session.add(action)
            db.session.flush()
            seq_to_action[rec.action_sequence] = action

        for crec in conflicts:
            resolution_action_id: Optional[int] = None
            if crec.resolution_action_sequence is not None:
                res_action = seq_to_action.get(crec.resolution_action_sequence)
                if res_action:
                    resolution_action_id = res_action.action_id

            conflict = DetectedConflict(
                rescheduling_run_id=run.rescheduling_run_id,
                connection_id=crec.connection_id,
                first_run_id=crec.first_run_id,
                second_run_id=crec.second_run_id,
                conflict_type=crec.conflict_type,
                conflict_start=crec.conflict_start,
                conflict_end=crec.conflict_end,
                resolved=crec.resolved,
                resolution_action_id=resolution_action_id,
            )
            db.session.add(conflict)

        db.session.commit()
        return run
