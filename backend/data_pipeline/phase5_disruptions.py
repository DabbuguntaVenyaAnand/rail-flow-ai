"""
data_pipeline/phase5_disruptions.py — Rail-Flow AI

Phase 5: Disruption scenario generation.
Reads historical actuals (Phase 4) and generates DisruptionEvent records.

Disruption types:
  - train_delay:        run with high delay (> 10 min)
  - segment_block:      corridor edge blocked for a time window
  - platform_conflict:  two trains at same station < 5 min apart
  - speed_restriction:  reduced-speed zone on a corridor edge

DisruptionEvent columns:
  disruption_id, disruption_type, station_code, connection_id,
  reported_at, expected_end_at, observed_delay_seconds,
  severity (str: low/medium/high), metadata_json, is_active

Usage:
    cd backend
    DATABASE_URL="postgresql+psycopg://railflow:railflow@localhost:5432/railflow_db" \\
    DEMO_MODE=false python3 -m data_pipeline.phase5_disruptions
"""

from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DELAY_THRESHOLD_S  = 10 * 60   # 10 minutes
SHORT_WINDOW_MIN   = 5          # platform conflict window
N_SYNTHETIC_BLOCKS = 20
N_SPEED_RESTRICT   = 10


def _severity(delay_s: float) -> str:
    if delay_s >= 3600:
        return "high"
    if delay_s >= 900:
        return "medium"
    return "low"


def run(app):
    import numpy as np
    from models import db, TimetableRun, TimetableEvent, DisruptionEvent, CorridorEdge

    rng = np.random.default_rng(99999)

    with app.app_context():

        # ── 1. Train-delay disruptions ────────────────────────────────────────
        print("[phase5] Scanning runs for high-delay events …")
        delay_count = 0
        # Track run_ids already covered to avoid duplicate inserts
        existing_run_ids: set[str] = set()
        for d_row in DisruptionEvent.query.filter_by(disruption_type="train_delay").all():
            run_id = (d_row.metadata_json or {}).get("run_id")
            if run_id:
                existing_run_ids.add(run_id)

        for run_obj in TimetableRun.query.all():
            if run_obj.run_id in existing_run_ids:
                continue

            events = (
                TimetableEvent.query
                .filter_by(run_id=run_obj.run_id)
                .order_by(TimetableEvent.stop_sequence)
                .all()
            )
            if not events:
                continue

            max_delay_s = 0
            worst_evt = None
            for e in events:
                if e.actual_arrival and e.scheduled_arrival:
                    d_s = (e.actual_arrival - e.scheduled_arrival).total_seconds()
                    if d_s > max_delay_s:
                        max_delay_s = d_s
                        worst_evt = e
                if e.actual_departure and e.scheduled_departure:
                    d_s = (e.actual_departure - e.scheduled_departure).total_seconds()
                    if d_s > max_delay_s:
                        max_delay_s = d_s
                        worst_evt = e

            if max_delay_s < DELAY_THRESHOLD_S or worst_evt is None:
                continue

            onset = (
                worst_evt.scheduled_arrival
                or worst_evt.scheduled_departure
                or datetime.now(timezone.utc)
            )
            d = DisruptionEvent(
                disruption_id=str(uuid.uuid4()),
                disruption_type="train_delay",
                station_code=worst_evt.station_code,
                reported_at=onset,
                expected_end_at=onset + timedelta(seconds=max_delay_s),
                observed_delay_seconds=int(max_delay_s),
                severity=_severity(max_delay_s),
                metadata_json={
                    "run_id":       run_obj.run_id,
                    "train_number": run_obj.train_number,
                    "service_date": str(run_obj.service_date),
                    "description":  f"Train {run_obj.train_number} delayed {int(max_delay_s)//60} min",
                },
                is_active=False,
            )
            db.session.add(d)
            existing_run_ids.add(run_obj.run_id)
            delay_count += 1

        db.session.commit()
        print(f"[phase5] {delay_count} train_delay disruptions created")

        # ── 2. Platform conflicts ─────────────────────────────────────────────
        print("[phase5] Detecting platform conflicts …")
        station_arrivals: dict[str, list[tuple[datetime, str, str]]] = {}

        for run_obj in TimetableRun.query.all():
            for e in TimetableEvent.query.filter_by(run_id=run_obj.run_id).all():
                arr = e.actual_arrival or e.scheduled_arrival
                if arr and e.station_code:
                    station_arrivals.setdefault(e.station_code, []).append(
                        (arr, run_obj.run_id, run_obj.train_number)
                    )

        conflict_count = 0
        for station_code, arrivals in station_arrivals.items():
            arrivals.sort(key=lambda x: x[0])
            for i in range(len(arrivals) - 1):
                t0, run_a, train_a = arrivals[i]
                t1, run_b, train_b = arrivals[i + 1]
                gap_min = (t1 - t0).total_seconds() / 60.0
                if 0 < gap_min < SHORT_WINDOW_MIN and run_a != run_b:
                    d = DisruptionEvent(
                        disruption_id=str(uuid.uuid4()),
                        disruption_type="platform_conflict",
                        station_code=station_code,
                        reported_at=t0,
                        expected_end_at=t1,
                        observed_delay_seconds=int(gap_min * 60),
                        severity="medium",
                        metadata_json={
                            "run_a":    run_a,
                            "run_b":    run_b,
                            "train_a":  train_a,
                            "train_b":  train_b,
                            "gap_min":  round(gap_min, 1),
                            "description": (
                                f"Platform conflict at {station_code}: "
                                f"{train_a} and {train_b} within {gap_min:.1f} min"
                            ),
                        },
                        is_active=False,
                    )
                    db.session.add(d)
                    conflict_count += 1

        db.session.commit()
        print(f"[phase5] {conflict_count} platform_conflict disruptions created")

        # ── 3. Synthetic segment blocks ───────────────────────────────────────
        print("[phase5] Generating synthetic segment_block disruptions …")
        edges = CorridorEdge.query.filter_by(is_enabled=True).limit(200).all()
        if not edges:
            print("[phase5] No edges — skipping blocks")
        else:
            edge_indices = rng.choice(
                len(edges), size=min(N_SYNTHETIC_BLOCKS, len(edges)), replace=False
            )
            block_count = 0
            base_t = datetime(2026, 3, 15, 10, 0, tzinfo=timezone.utc)
            for idx in edge_indices:
                edge = edges[int(idx)]
                onset = base_t + timedelta(hours=float(rng.uniform(0, 23)))
                dur_min = int(rng.integers(15, 90))
                d = DisruptionEvent(
                    disruption_id=str(uuid.uuid4()),
                    disruption_type="segment_block",
                    connection_id=edge.edge_id,
                    reported_at=onset,
                    expected_end_at=onset + timedelta(minutes=dur_min),
                    severity="high" if dur_min >= 60 else "medium",
                    metadata_json={
                        "from":        edge.from_station_id,
                        "to":          edge.to_station_id,
                        "is_blocked":  True,
                        "duration_min": dur_min,
                        "description": (
                            f"Synthetic block: {edge.from_station_id}→{edge.to_station_id}, "
                            f"{dur_min} min"
                        ),
                    },
                    is_active=False,
                )
                db.session.add(d)
                block_count += 1

            db.session.commit()
            print(f"[phase5] {block_count} segment_block disruptions created")

        # ── 4. Speed restrictions ─────────────────────────────────────────────
        print("[phase5] Generating synthetic speed_restriction disruptions …")
        if edges:
            sr_indices = rng.choice(
                len(edges), size=min(N_SPEED_RESTRICT, len(edges)), replace=False
            )
            sr_count = 0
            base_t = datetime(2026, 3, 16, 8, 0, tzinfo=timezone.utc)
            for idx in sr_indices:
                edge = edges[int(idx)]
                onset = base_t + timedelta(hours=float(rng.uniform(0, 48)))
                dur_min = int(rng.integers(30, 180))
                d = DisruptionEvent(
                    disruption_id=str(uuid.uuid4()),
                    disruption_type="speed_restriction",
                    connection_id=edge.edge_id,
                    reported_at=onset,
                    expected_end_at=onset + timedelta(minutes=dur_min),
                    severity="low",
                    metadata_json={
                        "from":        edge.from_station_id,
                        "to":          edge.to_station_id,
                        "is_blocked":  False,
                        "duration_min": dur_min,
                        "description": (
                            f"Speed restriction: {edge.from_station_id}→{edge.to_station_id}"
                        ),
                    },
                    is_active=False,
                )
                db.session.add(d)
                sr_count += 1

            db.session.commit()
            print(f"[phase5] {sr_count} speed_restriction disruptions created")

        total = DisruptionEvent.query.count()
        print(f"\n[phase5] Done. Total DisruptionEvents in DB: {total}")


if __name__ == "__main__":
    from app import create_app
    _app = create_app({
        "DEMO_MODE": False,
        "SQLALCHEMY_DATABASE_URI": os.environ.get(
            "DATABASE_URL",
            "postgresql+psycopg://railflow:railflow@localhost:5432/railflow_db"
        ),
    })
    run(_app)
