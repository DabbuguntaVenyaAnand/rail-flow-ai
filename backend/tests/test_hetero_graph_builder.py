"""
test_hetero_graph_builder.py — Phase 5.

All tests require torch + torch_geometric; skipped automatically if absent.
"""

from __future__ import annotations

import pytest

# Skip entire module if torch_geometric is not installed.
torch_geometric = pytest.importorskip(
    "torch_geometric", reason="torch_geometric not installed — skipping Phase 5 graph tests"
)
torch = pytest.importorskip("torch", reason="torch not installed")

from predictors.hetero_graph_builder import (
    HeteroGraphBuilder,
    STATION_FEAT_DIM,
    TRAIN_FEAT_DIM,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _snapshot(n_trains: int = 2, n_stops: int = 3, with_actuals: bool = False) -> dict:
    """Build a minimal snapshot_json with n_trains each making n_stops."""
    runs = []
    live = []
    station_pool = [f"S{i:02d}" for i in range(n_stops)]
    for t in range(n_trains):
        rid = f"r{t}"
        events = []
        for s in range(n_stops):
            ev = {
                "station_code": station_pool[s],
                "stop_sequence": s + 1,
                "scheduled_arrival": f"2026-06-13T0{6+s}:00:00+00:00",
                "scheduled_departure": f"2026-06-13T0{6+s}:10:00+00:00",
                "actual_arrival": (f"2026-06-13T0{6+s}:05:00+00:00" if with_actuals else None),
                "actual_departure": None,
                "min_dwell_seconds": 60,
            }
            events.append(ev)
        runs.append({"run_id": rid, "train_number": f"1230{t}", "events": events})
        live.append({"run_id": rid, "delay_seconds": t * 300})
    return {
        "t0": "2026-06-13T05:00:00+00:00",
        "runs": runs,
        "live_states": live,
        "disruptions": [],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Node counts
# ─────────────────────────────────────────────────────────────────────────────

def test_station_node_count():
    """Number of station nodes equals unique station codes in the snapshot."""
    snap = _snapshot(n_trains=3, n_stops=4)
    data = HeteroGraphBuilder().build(snap)
    assert data["station"].x.shape[0] == 4


def test_train_node_count():
    snap = _snapshot(n_trains=3, n_stops=2)
    data = HeteroGraphBuilder().build(snap)
    assert data["running_train"].x.shape[0] == 3


# ─────────────────────────────────────────────────────────────────────────────
# Node feature dimensions
# ─────────────────────────────────────────────────────────────────────────────

def test_station_feature_dim():
    snap = _snapshot()
    data = HeteroGraphBuilder().build(snap)
    assert data["station"].x.shape[1] == STATION_FEAT_DIM


def test_train_feature_dim():
    snap = _snapshot()
    data = HeteroGraphBuilder().build(snap)
    assert data["running_train"].x.shape[1] == TRAIN_FEAT_DIM


# ─────────────────────────────────────────────────────────────────────────────
# Edge shapes
# ─────────────────────────────────────────────────────────────────────────────

def test_scheduled_at_edges_count():
    """scheduled_at has n_trains * n_stops edges (one per stop per train)."""
    n_trains, n_stops = 2, 3
    snap = _snapshot(n_trains=n_trains, n_stops=n_stops)
    data = HeteroGraphBuilder().build(snap)
    ei = data["running_train", "scheduled_at", "station"].edge_index
    assert ei.shape == (2, n_trains * n_stops)


def test_at_station_edges_only_when_actuals_present():
    """at_station edges are 0 when no actual_arrival is recorded."""
    snap = _snapshot(with_actuals=False)
    data = HeteroGraphBuilder().build(snap)
    ei = data["running_train", "at_station", "station"].edge_index
    assert ei.shape[1] == 0


def test_at_station_edges_with_actuals():
    """at_station edges equal n_trains when every train has an actual arrival."""
    n_trains = 3
    snap = _snapshot(n_trains=n_trains, n_stops=2, with_actuals=True)
    data = HeteroGraphBuilder().build(snap)
    ei = data["running_train", "at_station", "station"].edge_index
    # Each train has one "current station" edge (last actual)
    assert ei.shape[1] == n_trains


# ─────────────────────────────────────────────────────────────────────────────
# Delayed train features
# ─────────────────────────────────────────────────────────────────────────────

def test_delayed_train_is_delayed_flag():
    """Train with delay ≥ 300 s should have is_delayed feature == 1.0."""
    snap = _snapshot(n_trains=2, n_stops=1)
    # r0 has delay=0, r1 has delay=300
    data = HeteroGraphBuilder().build(snap)
    # running_train.x[:, 2] is the is_delayed feature
    is_delayed = data["running_train"].x[:, 2].tolist()
    assert is_delayed[0] == pytest.approx(0.0)
    assert is_delayed[1] == pytest.approx(1.0)


# ─────────────────────────────────────────────────────────────────────────────
# Edge cases
# ─────────────────────────────────────────────────────────────────────────────

def test_empty_snapshot_does_not_crash():
    """Empty snapshot must not raise; returns minimal valid HeteroData."""
    snap = {"t0": "2026-06-13T05:00:00+00:00", "runs": [], "live_states": [], "disruptions": []}
    data = HeteroGraphBuilder().build(snap)
    assert data["station"].x.shape[0] >= 1
    assert data["running_train"].x.shape[0] >= 1
