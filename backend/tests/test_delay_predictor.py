"""
test_delay_predictor.py — Unit tests for DelayPredictor protocol and
HistoricalBaselinePredictor.

All tests are pure (no DB required); they operate on hand-built snapshot dicts.
"""

from __future__ import annotations

import pytest

from predictors.base import DelayEstimate, DelayPredictor
from predictors.historical_baseline import (
    HistoricalBaselinePredictor,
    PEAK_MULTIPLIER,
    P90_RATIO,
    SHORT_HEADWAY_MULTIPLIER,
    SHORT_HEADWAY_SECONDS,
    _peak_factor,
    _detect_short_headway,
    _event_based_delays,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _snapshot(
    runs=None,
    live_states=None,
    t0="2026-06-13T05:00:00+00:00",
) -> dict:
    """Build a minimal snapshot_json dict."""
    return {
        "t0": t0,
        "horizon_end": "2026-06-13T15:00:00+00:00",
        "runs": runs or [],
        "live_states": live_states or [],
        "disruptions": [],
    }


def _run(run_id: str, events: list[dict]) -> dict:
    return {"run_id": run_id, "events": events}


def _event(
    station: str,
    seq: int,
    sched_arr=None,
    act_arr=None,
    sched_dep=None,
    act_dep=None,
) -> dict:
    return {
        "station_code": station,
        "stop_sequence": seq,
        "scheduled_arrival": sched_arr,
        "actual_arrival": act_arr,
        "scheduled_departure": sched_dep,
        "actual_departure": act_dep,
        "min_dwell_seconds": 60,
    }


def _live(run_id: str, delay_seconds: int) -> dict:
    return {"run_id": run_id, "delay_seconds": delay_seconds}


# ─────────────────────────────────────────────────────────────────────────────
# Protocol conformance
# ─────────────────────────────────────────────────────────────────────────────

def test_predictor_satisfies_protocol():
    p = HistoricalBaselinePredictor()
    assert isinstance(p, DelayPredictor), (
        "HistoricalBaselinePredictor must satisfy the DelayPredictor protocol"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Basic contract
# ─────────────────────────────────────────────────────────────────────────────

def test_predict_returns_list():
    snap = _snapshot(
        runs=[_run("r1", [])],
        live_states=[_live("r1", 300)],
    )
    p = HistoricalBaselinePredictor()
    result = p.predict(snap, horizons=[30])
    assert isinstance(result, list)
    assert all(isinstance(e, DelayEstimate) for e in result)


def test_predict_one_estimate_per_run_per_horizon():
    snap = _snapshot(
        runs=[_run("r1", []), _run("r2", [])],
        live_states=[_live("r1", 0), _live("r2", 0)],
    )
    p = HistoricalBaselinePredictor()
    result = p.predict(snap, horizons=[15, 30, 60])
    assert len(result) == 6   # 2 runs × 3 horizons


def test_predict_empty_horizons_returns_empty():
    snap = _snapshot(runs=[_run("r1", [])])
    p = HistoricalBaselinePredictor()
    assert p.predict(snap, horizons=[]) == []


def test_predict_no_runs_returns_empty():
    snap = _snapshot()
    p = HistoricalBaselinePredictor()
    assert p.predict(snap, horizons=[30]) == []


# ─────────────────────────────────────────────────────────────────────────────
# Delay values
# ─────────────────────────────────────────────────────────────────────────────

def test_zero_delay_when_no_live_state_and_no_actuals():
    snap = _snapshot(runs=[_run("r1", [
        _event("A", 1, sched_dep="2026-06-13T06:00:00+00:00"),
    ])])
    p = HistoricalBaselinePredictor()
    ests = p.predict(snap, horizons=[30])
    assert ests[0].p50_delay_seconds == 0
    assert ests[0].p90_delay_seconds == 0


def test_p50_matches_live_delay():
    delay = 900
    snap = _snapshot(
        runs=[_run("r1", [])],
        live_states=[_live("r1", delay)],
        t0="2026-06-13T05:00:00+00:00",  # not peak hour
    )
    p = HistoricalBaselinePredictor()
    ests = p.predict(snap, horizons=[30])
    assert ests[0].p50_delay_seconds == delay


def test_p90_ge_p50():
    snap = _snapshot(
        runs=[_run("r1", [])],
        live_states=[_live("r1", 600)],
    )
    p = HistoricalBaselinePredictor()
    ests = p.predict(snap, horizons=[30])
    assert ests[0].p90_delay_seconds >= ests[0].p50_delay_seconds


def test_p90_ratio():
    delay = 1000
    snap = _snapshot(
        runs=[_run("r1", [])],
        live_states=[_live("r1", delay)],
        t0="2026-06-13T05:00:00+00:00",  # not peak
    )
    p = HistoricalBaselinePredictor()
    ests = p.predict(snap, horizons=[30])
    expected_p90 = round(delay * P90_RATIO)
    assert ests[0].p90_delay_seconds == expected_p90


# ─────────────────────────────────────────────────────────────────────────────
# Peak-hour multiplier
# ─────────────────────────────────────────────────────────────────────────────

def test_peak_factor_during_morning_peak():
    """IST morning peak 07:00–09:00 = UTC 01:30–03:30."""
    from datetime import datetime, timezone
    t0_peak = datetime(2026, 6, 13, 2, 0, 0, tzinfo=timezone.utc)  # 02:00 UTC = 07:30 IST
    assert _peak_factor(t0_peak) == pytest.approx(PEAK_MULTIPLIER)


def test_peak_factor_outside_peak():
    from datetime import datetime, timezone
    t0_off = datetime(2026, 6, 13, 5, 0, 0, tzinfo=timezone.utc)   # 05:00 UTC = 10:30 IST
    assert _peak_factor(t0_off) == pytest.approx(1.0)


def test_peak_multiplier_increases_p50():
    delay = 600
    snap_peak = _snapshot(
        runs=[_run("r1", [])],
        live_states=[_live("r1", delay)],
        t0="2026-06-13T02:00:00+00:00",  # peak UTC (IST morning)
    )
    snap_off = _snapshot(
        runs=[_run("r1", [])],
        live_states=[_live("r1", delay)],
        t0="2026-06-13T05:00:00+00:00",  # off-peak
    )
    p = HistoricalBaselinePredictor()
    p50_peak = p.predict(snap_peak, [30])[0].p50_delay_seconds
    p50_off  = p.predict(snap_off,  [30])[0].p50_delay_seconds
    assert p50_peak > p50_off


# ─────────────────────────────────────────────────────────────────────────────
# Short-headway multiplier
# ─────────────────────────────────────────────────────────────────────────────

def test_short_headway_detected():
    """Two trains depart the same station < SHORT_HEADWAY_SECONDS apart."""
    runs = [
        _run("r1", [_event("A", 1, sched_dep="2026-06-13T06:00:00+00:00")]),
        _run("r2", [_event("A", 1, sched_dep="2026-06-13T06:10:00+00:00")]),  # 600 s < 900 s
    ]
    hw = _detect_short_headway(_snapshot(runs=runs))
    assert "r2" in hw


def test_no_short_headway_when_gap_sufficient():
    """Two trains depart > SHORT_HEADWAY_SECONDS apart → no flag."""
    runs = [
        _run("r1", [_event("A", 1, sched_dep="2026-06-13T06:00:00+00:00")]),
        _run("r2", [_event("A", 1, sched_dep="2026-06-13T06:20:00+00:00")]),  # 1200 s > 900 s
    ]
    hw = _detect_short_headway(_snapshot(runs=runs))
    assert "r2" not in hw


def test_short_headway_multiplier_applied():
    runs = [
        _run("r1", [_event("A", 1, sched_dep="2026-06-13T06:00:00+00:00")]),
        _run("r2", [_event("A", 1, sched_dep="2026-06-13T06:10:00+00:00")]),
    ]
    live = [_live("r1", 0), _live("r2", 600)]
    snap = _snapshot(runs=runs, live_states=live, t0="2026-06-13T05:00:00+00:00")
    p = HistoricalBaselinePredictor()
    ests = {e.run_id: e for e in p.predict(snap, [30])}
    # r2 follows r1 within 900 s → multiplier applies
    assert ests["r2"].p50_delay_seconds == round(600 * SHORT_HEADWAY_MULTIPLIER)


# ─────────────────────────────────────────────────────────────────────────────
# Determinism
# ─────────────────────────────────────────────────────────────────────────────

def test_predictor_is_deterministic():
    snap = _snapshot(
        runs=[_run("r1", []), _run("r2", [])],
        live_states=[_live("r1", 900), _live("r2", 300)],
    )
    p = HistoricalBaselinePredictor()
    r1 = p.predict(snap, [15, 30, 60])
    r2 = p.predict(snap, [15, 30, 60])
    assert [(e.run_id, e.p50_delay_seconds) for e in r1] == \
           [(e.run_id, e.p50_delay_seconds) for e in r2]


# ─────────────────────────────────────────────────────────────────────────────
# Model version
# ─────────────────────────────────────────────────────────────────────────────

def test_model_version_set():
    snap = _snapshot(runs=[_run("r1", [])], live_states=[_live("r1", 0)])
    p = HistoricalBaselinePredictor()
    ests = p.predict(snap, [30])
    assert ests[0].model_version == HistoricalBaselinePredictor.MODEL_VERSION


# ─────────────────────────────────────────────────────────────────────────────
# Integration: predict with demo snapshot
# ─────────────────────────────────────────────────────────────────────────────

def test_predictor_with_demo_snapshot(app, _setup_demo_data):
    """HistoricalBaselinePredictor works on a real demo snapshot."""
    with app.app_context():
        from services.snapshot_service import SnapshotService
        from datetime import datetime, timezone

        t0 = datetime(2026, 6, 13, 5, 0, 0, tzinfo=timezone.utc)
        snap = SnapshotService(horizon_minutes=600).build(t0=t0, trigger_type="test")

        p = HistoricalBaselinePredictor()
        ests = p.predict(snap.snapshot_json, horizons=[15, 30, 60])

        # 5 runs × 3 horizons
        assert len(ests) == 15
        for e in ests:
            assert e.p90_delay_seconds >= e.p50_delay_seconds
            assert e.p50_delay_seconds >= 0
