"""
services/snapshot_service.py — Rail-Flow AI

SnapshotService builds a point-in-time OperationalSnapshot from the live DB
state.  The resulting row in operational_snapshots can be used to reproduce
any past rescheduling run and is the entry point for Algorithm 2 (core
rescheduling procedure).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from models import (
    db,
    TimetableRun,
    TimetableEvent,
    LiveTrainState,
    DisruptionEvent,
    OperationalSnapshot,
)


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None


class SnapshotService:
    """
    Serialises the current network state into an OperationalSnapshot row.

    Usage::

        svc = SnapshotService(horizon_minutes=60)
        snap = svc.build(t0=datetime.now(timezone.utc),
                         trigger_type="disruption",
                         trigger_reference="d0000001-0000-0000-0000-000000000001")
    """

    def __init__(self, horizon_minutes: int = 60) -> None:
        self.horizon_minutes = horizon_minutes

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def build(
        self,
        t0: datetime,
        trigger_type: str,
        trigger_reference: Optional[str] = None,
    ) -> OperationalSnapshot:
        """
        Capture network state at *t0* and persist to operational_snapshots.

        :param t0: Reference time (tz-aware UTC).
        :param trigger_type: One of ``manual``, ``scheduled``, ``disruption``.
        :param trigger_reference: Optional FK-style string (e.g. disruption_id).
        :returns: The newly inserted :class:`OperationalSnapshot` ORM row.
        """
        horizon_end = datetime(
            t0.year, t0.month, t0.day,
            t0.hour, t0.minute, t0.second,
            tzinfo=t0.tzinfo,
        )
        # Add horizon in seconds to avoid timedelta import collision
        from datetime import timedelta
        horizon_end = t0 + timedelta(minutes=self.horizon_minutes)

        runs_data = self._collect_runs(t0, horizon_end)
        live_states_data = self._collect_live_states(runs_data)
        disruptions_data = self._collect_disruptions()

        snapshot_json = {
            "t0": t0.isoformat(),
            "horizon_end": horizon_end.isoformat(),
            "runs": runs_data,
            "live_states": live_states_data,
            "disruptions": disruptions_data,
        }

        snap = OperationalSnapshot(
            captured_at=t0,
            trigger_type=trigger_type,
            trigger_reference=trigger_reference,
            snapshot_json=snapshot_json,
        )
        db.session.add(snap)
        db.session.commit()
        return snap

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _collect_runs(
        self, t0: datetime, horizon_end: datetime
    ) -> list[dict]:
        """Return all TimetableRuns that have at least one event in [t0, horizon_end]."""
        from datetime import timedelta

        # Find runs with any scheduled departure/arrival in the horizon window.
        run_ids_in_window = (
            db.session.query(TimetableEvent.run_id)
            .filter(
                db.or_(
                    db.and_(
                        TimetableEvent.scheduled_departure.isnot(None),
                        TimetableEvent.scheduled_departure >= t0,
                        TimetableEvent.scheduled_departure <= horizon_end,
                    ),
                    db.and_(
                        TimetableEvent.scheduled_arrival.isnot(None),
                        TimetableEvent.scheduled_arrival >= t0,
                        TimetableEvent.scheduled_arrival <= horizon_end,
                    ),
                )
            )
            .distinct()
            .all()
        )
        run_id_set = {r[0] for r in run_ids_in_window}

        result = []
        for run_id in sorted(run_id_set):
            run = db.session.get(TimetableRun, run_id)
            if run is None:
                continue
            events = [
                {
                    "event_id": ev.event_id,
                    "station_code": ev.station_code,
                    "stop_sequence": ev.stop_sequence,
                    "scheduled_arrival": _iso(ev.scheduled_arrival),
                    "scheduled_departure": _iso(ev.scheduled_departure),
                    "min_dwell_seconds": ev.min_dwell_seconds,
                    "actual_arrival": _iso(ev.actual_arrival),
                    "actual_departure": _iso(ev.actual_departure),
                }
                for ev in run.events
            ]
            result.append(
                {
                    "run_id": run.run_id,
                    "train_number": run.train_number,
                    "service_date": run.service_date.isoformat(),
                    "run_status": run.run_status,
                    "events": events,
                }
            )
        return result

    def _collect_live_states(self, runs_data: list[dict]) -> list[dict]:
        """Return the most-recent LiveTrainState for each run in *runs_data*."""
        result = []
        for run_info in runs_data:
            run_id = run_info["run_id"]
            latest = (
                LiveTrainState.query.filter_by(run_id=run_id)
                .order_by(LiveTrainState.observed_at.desc())
                .first()
            )
            if latest is None:
                continue
            result.append(latest.to_dict())
        return result

    def _collect_disruptions(self) -> list[dict]:
        """Return all currently active DisruptionEvents."""
        active = DisruptionEvent.query.filter_by(is_active=True).all()
        return [d.to_dict() for d in active]
