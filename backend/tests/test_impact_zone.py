"""
test_impact_zone.py — Unit tests for ImpactZoneService (Algorithm 1).

Pure-logic tests use hand-built snapshot dicts with no DB.
Integration tests use the demo snapshot fixture.
"""

from __future__ import annotations

import pytest

from predictors.base import DelayEstimate
from services.impact_zone_service import ImpactZoneService, _min_headway_gap


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _snapshot(runs=None, live_states=None) -> dict:
    return {
        "t0": "2026-06-13T05:00:00+00:00",
        "runs": runs or [],
        "live_states": live_states or [],
        "disruptions": [],
    }


def _live(run_id: str, delay_s: int) -> dict:
    return {"run_id": run_id, "delay_seconds": delay_s}


def _est(run_id: str, p50: int) -> DelayEstimate:
    return DelayEstimate(
        run_id=run_id,
        horizon_minutes=30,
        p50_delay_seconds=p50,
        p90_delay_seconds=round(p50 * 1.6),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Direct-observation threshold (theta_obs)
# ─────────────────────────────────────────────────────────────────────────────

def test_delayed_train_included():
    """Train with delay >= theta_obs (5 min = 300 s) is in the zone."""
    svc = ImpactZoneService(theta_obs_minutes=5)
    snap = _snapshot(
        runs=[{"run_id": "r1"}, {"run_id": "r2"}],
        live_states=[_live("r1", 900), _live("r2", 0)],
    )
    zone = svc.select(snap, predictions=[])
    assert "r1" in zone


def test_non_delayed_train_excluded_without_predictions():
    """Train with zero delay and no predictions is NOT in the zone."""
    svc = ImpactZoneService(theta_obs_minutes=5)
    snap = _snapshot(
        runs=[{"run_id": "r1"}, {"run_id": "r2"}],
        live_states=[_live("r1", 0), _live("r2", 0)],
    )
    zone = svc.select(snap, predictions=[])
    assert "r1" not in zone
    assert "r2" not in zone


def test_exactly_at_threshold_included():
    """delay_seconds == theta_obs * 60 is on the boundary → include."""
    svc = ImpactZoneService(theta_obs_minutes=5)
    snap = _snapshot(
        runs=[{"run_id": "r1"}],
        live_states=[_live("r1", 300)],  # exactly 5 min
    )
    zone = svc.select(snap, predictions=[])
    assert "r1" in zone


def test_just_below_threshold_excluded():
    svc = ImpactZoneService(theta_obs_minutes=5)
    snap = _snapshot(
        runs=[{"run_id": "r1"}],
        live_states=[_live("r1", 299)],
    )
    zone = svc.select(snap, predictions=[])
    assert "r1" not in zone


# ─────────────────────────────────────────────────────────────────────────────
# Prediction-based threshold (theta_pred)
# ─────────────────────────────────────────────────────────────────────────────

def test_high_prediction_adds_train():
    """Train with p50 >= theta_pred (8 min = 480 s) is included even if current delay = 0."""
    svc = ImpactZoneService(theta_pred_minutes=8)
    snap = _snapshot(
        runs=[{"run_id": "r1"}],
        live_states=[_live("r1", 0)],
    )
    predictions = [_est("r1", 480)]
    zone = svc.select(snap, predictions=predictions)
    assert "r1" in zone


def test_low_prediction_does_not_add_train():
    svc = ImpactZoneService(theta_pred_minutes=8)
    snap = _snapshot(
        runs=[{"run_id": "r1"}],
        live_states=[_live("r1", 0)],
    )
    predictions = [_est("r1", 100)]
    zone = svc.select(snap, predictions=predictions)
    assert "r1" not in zone


# ─────────────────────────────────────────────────────────────────────────────
# Unknown run in live_states is ignored
# ─────────────────────────────────────────────────────────────────────────────

def test_unknown_run_in_live_states_ignored():
    svc = ImpactZoneService()
    snap = _snapshot(
        runs=[{"run_id": "r1"}],
        live_states=[_live("r1", 0), _live("r999", 9999)],  # r999 not in runs
    )
    zone = svc.select(snap, predictions=[])
    assert "r999" not in zone


# ─────────────────────────────────────────────────────────────────────────────
# MAX cap
# ─────────────────────────────────────────────────────────────────────────────

def test_max_impacted_trains_cap():
    """When more trains are delayed than the cap, only top-delay trains kept."""
    svc = ImpactZoneService(max_impacted_trains=2)
    runs = [{"run_id": f"r{i}"} for i in range(5)]
    live = [_live(f"r{i}", (i + 1) * 100) for i in range(5)]  # r0=100s...r4=500s
    snap = _snapshot(runs=runs, live_states=live)
    zone = svc.select(snap, predictions=[])
    # Only theta_obs >= 300 s → r2(300), r3(400), r4(500) → capped to 2 highest
    assert len(zone) <= 2
    assert "r4" in zone   # highest delay
    assert "r3" in zone   # second highest


# ─────────────────────────────────────────────────────────────────────────────
# Empty snapshot
# ─────────────────────────────────────────────────────────────────────────────

def test_empty_snapshot_returns_empty():
    svc = ImpactZoneService()
    zone = svc.select(_snapshot(), predictions=[])
    assert zone == set()


# ─────────────────────────────────────────────────────────────────────────────
# Integration: demo snapshot
# ─────────────────────────────────────────────────────────────────────────────

def test_impact_zone_with_demo_data(app, _setup_demo_data):
    """
    With demo data, runs 12301/12303/12305 are delayed >= 5 min and should
    appear in the impact zone.  Runs 12302/12304 (0 delay) should be absent
    unless propagation adds them.
    """
    with app.app_context():
        from services.snapshot_service import SnapshotService
        from predictors.historical_baseline import HistoricalBaselinePredictor
        from datetime import datetime, timezone

        t0 = datetime(2026, 6, 13, 5, 0, 0, tzinfo=timezone.utc)
        snap = SnapshotService(horizon_minutes=600).build(t0=t0, trigger_type="test")

        predictor = HistoricalBaselinePredictor()
        predictions = predictor.predict(snap.snapshot_json, horizons=[30])

        svc = ImpactZoneService()
        zone = svc.select(snap.snapshot_json, predictions)

        # run_ids for 12301, 12303, 12305
        delayed_ids = {
            "00000001-0000-0000-0000-000000000001",   # 12301: 900 s
            "00000001-0000-0000-0000-000000000003",   # 12303: 900 s
            "00000001-0000-0000-0000-000000000005",   # 12305: 1200 s
        }
        for run_id in delayed_ids:
            assert run_id in zone, f"Expected {run_id} in impact zone"

        # Zone must not be empty
        assert len(zone) >= 3


def test_impact_zone_all_runs_when_none_delayed(app, _setup_demo_data):
    """
    When no trains are delayed (hypothetical), the rescheduling pipeline
    falls back to all runs.  The zone itself may be empty.
    """
    with app.app_context():
        from services.snapshot_service import SnapshotService
        from datetime import datetime, timezone

        t0 = datetime(2026, 6, 13, 5, 0, 0, tzinfo=timezone.utc)
        snap = SnapshotService(horizon_minutes=600).build(t0=t0, trigger_type="test")

        svc = ImpactZoneService()
        # Pass empty predictions with all delays zeroed out manually
        snap_copy = dict(snap.snapshot_json)
        snap_copy["live_states"] = [
            {**ls, "delay_seconds": 0}
            for ls in snap.snapshot_json.get("live_states", [])
        ]
        zone = svc.select(snap_copy, predictions=[])
        # No delays → zone is empty (caller falls back to all runs)
        assert zone == set()
