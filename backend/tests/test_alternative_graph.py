"""
test_alternative_graph.py — Unit tests for AlternativeGraph.

Tests that don't need DB work with in-memory graph construction.
Tests that build via AlternativeGraph.build() use the demo snapshot fixture.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pytest

from rescheduling.alternative_graph import (
    AlternativeGraph,
    AltPair,
    Arc,
    EventNode,
    SOURCE,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _t(h: int, m: int = 0) -> datetime:
    return datetime(2026, 6, 13, h, m, 0, tzinfo=timezone.utc)


def _make_simple_graph() -> AlternativeGraph:
    """
    Two trains on one shared segment, one alternative pair.
    Run A: DEP(A,1) at 06:00 → ARR(A,2) at 07:00
    Run B: DEP(B,1) at 06:05 → ARR(B,2) at 07:05
    """
    g = AlternativeGraph()
    g.t0_seconds = _t(6, 0).timestamp()
    g.commit_window_seconds = 600.0

    base = _t(6, 0).timestamp()

    dep_a1 = EventNode("run-a", 1, "DEP")
    arr_a2 = EventNode("run-a", 2, "ARR")
    dep_b1 = EventNode("run-b", 1, "DEP")
    arr_b2 = EventNode("run-b", 2, "ARR")

    for node in (dep_a1, arr_a2, dep_b1, arr_b2):
        g.nodes.add(node)

    # Scheduled times
    g.scheduled_times = {
        dep_a1: base,
        arr_a2: base + 3600,
        dep_b1: base + 300,        # 5 min after A
        arr_b2: base + 300 + 3600,
    }
    g.station_for = {
        dep_a1: "X", arr_a2: "Y",
        dep_b1: "X", arr_b2: "Y",
    }

    # Release arcs
    for node, ts in g.scheduled_times.items():
        g.fixed_arcs.append(Arc(SOURCE, node, ts - g.t0_seconds))

    # Running arcs
    g.fixed_arcs.append(Arc(dep_a1, arr_a2, 3600.0))
    g.fixed_arcs.append(Arc(dep_b1, arr_b2, 3600.0))

    # Alternative pair: A before B or B before A
    h_min = 300.0
    fwd = Arc(arr_a2, dep_b1, h_min)   # A first: ARR(A,2) → DEP(B,1)
    bwd = Arc(arr_b2, dep_a1, h_min)   # B first: ARR(B,2) → DEP(A,1)

    pair_id = "test-pair-001"
    pair = AltPair(
        pair_id=pair_id, edge_id=42,
        run_i="run-a", dep_stop_i=1, arr_stop_i=2,
        run_j="run-b", dep_stop_j=1, arr_stop_j=2,
        fwd=fwd, bwd=bwd,
    )
    g.alt_pairs[pair_id] = pair
    g.selections[pair_id] = None

    return g


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_unresolved_pairs_initially_all_none():
    g = _make_simple_graph()
    assert len(g.unresolved_pairs()) == 1
    assert g.unresolved_pairs()[0].pair_id == "test-pair-001"


def test_select_arc_fwd_removes_from_unresolved():
    g = _make_simple_graph()
    g.select_arc("test-pair-001", 0)
    assert g.unresolved_pairs() == []
    assert g.selections["test-pair-001"] == 0


def test_select_arc_bwd():
    g = _make_simple_graph()
    g.select_arc("test-pair-001", 1)
    assert g.selections["test-pair-001"] == 1


def test_select_arc_invalid_direction():
    g = _make_simple_graph()
    with pytest.raises(ValueError):
        g.select_arc("test-pair-001", 2)


def test_select_arc_unknown_pair_id():
    g = _make_simple_graph()
    with pytest.raises(KeyError):
        g.select_arc("does-not-exist", 0)


def test_active_arcs_includes_only_selected():
    g = _make_simple_graph()
    # Before selection: no alt arc
    fixed_count = len(g.fixed_arcs)
    assert len(g.active_arcs()) == fixed_count

    g.select_arc("test-pair-001", 0)
    assert len(g.active_arcs()) == fixed_count + 1
    # The added arc should be the fwd arc
    added = [a for a in g.active_arcs() if a not in g.fixed_arcs]
    assert len(added) == 1
    assert added[0].dst.run_id == "run-b"


def test_copy_is_independent():
    g = _make_simple_graph()
    g2 = g.copy()
    g2.select_arc("test-pair-001", 0)

    # Original should be unmodified
    assert g.selections["test-pair-001"] is None
    assert g2.selections["test-pair-001"] == 0


def test_arc_selection_returns_snapshot():
    g = _make_simple_graph()
    g.select_arc("test-pair-001", 1)
    snap = g.arc_selection()
    assert snap["test-pair-001"] == 1
    # Mutating snap should not affect g
    snap["test-pair-001"] = 0
    assert g.selections["test-pair-001"] == 1


def test_apply_warm_start():
    g = _make_simple_graph()
    g.apply_warm_start({"test-pair-001": 0})
    assert g.selections["test-pair-001"] == 0


def test_apply_warm_start_ignores_unknown():
    g = _make_simple_graph()
    g.apply_warm_start({"unknown-pair": 1})
    assert g.unresolved_pairs()[0].pair_id == "test-pair-001"


def test_build_from_demo_snapshot(app, _setup_demo_data):
    """
    AlternativeGraph.build() should detect the shared segments between
    run 12301 and run 12305 (both use C019↔C031 and C031↔C030).
    """
    with app.app_context():
        from services.snapshot_service import SnapshotService

        svc = SnapshotService(horizon_minutes=600)
        t0 = _t(5, 0)
        snapshot = svc.build(t0=t0, trigger_type="manual")

        run_ids = {r["run_id"] for r in snapshot.snapshot_json["runs"]}
        g = AlternativeGraph.build(
            snapshot_json=snapshot.snapshot_json,
            impact_run_ids=run_ids,
            t0=t0,
            commit_window_minutes=10,
            horizon_minutes=600,
        )

        assert len(g.nodes) > 0, "Graph should have event nodes"
        assert len(g.fixed_arcs) > 0, "Graph should have fixed arcs"
        # Runs 12301 and 12305 share two segments — expect 2 alternative pairs
        assert len(g.alt_pairs) >= 1, (
            "Expected at least one alternative pair for 12301 ↔ 12305"
        )
        # All pairs should start unresolved
        assert all(g.selections[pid] is None for pid in g.alt_pairs)
