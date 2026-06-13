"""
test_residual_model.py — Unit tests for ResidualModel (Phase 7).

All tests are pure (no DB, no Flask app context required).
"""

from __future__ import annotations

import pytest

from predictors.residual_model import ResidualModel


# ─────────────────────────────────────────────────────────────────────────────
# Construction and population
# ─────────────────────────────────────────────────────────────────────────────

def test_empty_bucket_returns_zero():
    """Sample from an empty model must return 0.0."""
    model = ResidualModel()
    r = model.sample("STA", "12301", 30, scenario_index=0)
    assert r == 0.0


def test_single_residual_always_returned():
    """With one residual, every scenario_index returns that same value."""
    model = ResidualModel()
    model.populate("STA", "12301", 30, residual_seconds=120.0)
    for k in range(16):
        assert model.sample("STA", "12301", 30, k) == pytest.approx(120.0)


def test_sorting_ascending():
    """
    Residuals are sorted ascending; scenario 0 = most optimistic,
    scenario N-1 = most pessimistic.
    """
    model = ResidualModel()
    for v in [300.0, 100.0, 200.0]:
        model.populate("STA", "12301", 30, residual_seconds=v)

    assert model.sample("STA", "12301", 30, 0) == pytest.approx(100.0)   # min
    assert model.sample("STA", "12301", 30, 1) == pytest.approx(200.0)
    assert model.sample("STA", "12301", 30, 2) == pytest.approx(300.0)   # max


def test_index_wraps_modulo():
    """scenario_index wraps around using modulo len(bucket)."""
    model = ResidualModel()
    model.populate("STA", "12301", 30, residual_seconds=50.0)
    model.populate("STA", "12301", 30, residual_seconds=100.0)

    # sorted: [50, 100]; K=16 → indices wrap
    assert model.sample("STA", "12301", 30, 0) == pytest.approx(50.0)
    assert model.sample("STA", "12301", 30, 1) == pytest.approx(100.0)
    assert model.sample("STA", "12301", 30, 2) == pytest.approx(50.0)    # wraps
    assert model.sample("STA", "12301", 30, 3) == pytest.approx(100.0)


def test_bucket_key_includes_horizon():
    """Different horizon_minutes are distinct buckets."""
    model = ResidualModel()
    model.populate("STA", "12301", 15, residual_seconds=60.0)
    model.populate("STA", "12301", 30, residual_seconds=90.0)

    assert model.sample("STA", "12301", 15, 0) == pytest.approx(60.0)
    assert model.sample("STA", "12301", 30, 0) == pytest.approx(90.0)


def test_bucket_key_includes_train_number():
    """Different train numbers are distinct buckets."""
    model = ResidualModel()
    model.populate("STA", "12301", 30, residual_seconds=60.0)
    model.populate("STA", "12302", 30, residual_seconds=120.0)

    assert model.sample("STA", "12301", 30, 0) == pytest.approx(60.0)
    assert model.sample("STA", "12302", 30, 0) == pytest.approx(120.0)


def test_fallback_to_station_when_train_missing():
    """
    When the exact (station, train_number, horizon) bucket is missing,
    fall back to any bucket with the same (station, horizon).
    """
    model = ResidualModel()
    model.populate("STA", "12301", 30, residual_seconds=75.0)

    # Query for a different train at the same station
    r = model.sample("STA", "12999", 30, 0)
    assert r == pytest.approx(75.0)


def test_no_cross_station_fallback():
    """Fallback only looks within the same station_code."""
    model = ResidualModel()
    model.populate("STA_A", "12301", 30, residual_seconds=100.0)

    # No data for STA_B → returns 0.0
    r = model.sample("STA_B", "12301", 30, 0)
    assert r == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# sort_cache invalidation
# ─────────────────────────────────────────────────────────────────────────────

def test_sort_cache_invalidated_after_populate():
    """Adding a new residual below existing ones re-sorts correctly."""
    model = ResidualModel()
    model.populate("STA", "12301", 30, residual_seconds=200.0)
    assert model.sample("STA", "12301", 30, 0) == pytest.approx(200.0)

    model.populate("STA", "12301", 30, residual_seconds=50.0)
    assert model.sample("STA", "12301", 30, 0) == pytest.approx(50.0)    # cache invalidated


# ─────────────────────────────────────────────────────────────────────────────
# sample_run_perturbations
# ─────────────────────────────────────────────────────────────────────────────

def test_sample_run_perturbations_returns_per_stop_map():
    model = ResidualModel()
    model.populate("A", "12301", 30, residual_seconds=10.0)
    model.populate("B", "12301", 30, residual_seconds=20.0)

    stop_stations = {1: "A", 2: "B"}
    result = model.sample_run_perturbations(
        run_id="run1", train_number="12301",
        stop_stations=stop_stations, horizon_minutes=30, scenario_index=0,
    )

    assert result[("run1", 1)] == pytest.approx(10.0)
    assert result[("run1", 2)] == pytest.approx(20.0)


# ─────────────────────────────────────────────────────────────────────────────
# build_from_snapshot
# ─────────────────────────────────────────────────────────────────────────────

def test_build_from_snapshot_with_actuals():
    """build_from_snapshot populates residuals from actual − scheduled."""
    snap = {
        "runs": [
            {
                "run_id": "r1",
                "train_number": "12301",
                "events": [
                    {
                        "station_code": "HWH",
                        "stop_sequence": 1,
                        "scheduled_arrival": "2026-06-13T06:00:00+00:00",
                        "actual_arrival":    "2026-06-13T06:15:00+00:00",
                    },
                ],
            }
        ]
    }
    model = ResidualModel.build_from_snapshot(snap, horizon_minutes=30)
    r = model.sample("HWH", "12301", 30, 0)
    # residual = 15 min = 900 s; no p50 adjustment
    assert r == pytest.approx(900.0)


def test_build_from_snapshot_skips_missing_actuals():
    """Events without actual_arrival should not add residuals."""
    snap = {
        "runs": [
            {
                "run_id": "r1",
                "train_number": "12301",
                "events": [
                    {
                        "station_code": "HWH",
                        "stop_sequence": 1,
                        "scheduled_arrival": "2026-06-13T06:00:00+00:00",
                        "actual_arrival": None,
                    },
                ],
            }
        ]
    }
    model = ResidualModel.build_from_snapshot(snap, horizon_minutes=30)
    r = model.sample("HWH", "12301", 30, 0)
    assert r == 0.0
