"""
test_greedy_policy.py — Unit tests for GreedyPolicy (Algorithm 4).

Tests use hand-built AlternativeGraph instances so no DB is required.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from rescheduling.alternative_graph import (
    AlternativeGraph,
    AltPair,
    Arc,
    EventNode,
    SOURCE,
)
from rescheduling.feasibility import FeasibilityShield
from rescheduling.fallback import HoldFallback
from policies.greedy_policy import GreedyPolicy


def _t(h: int, m: int = 0) -> float:
    return datetime(2026, 6, 13, h, m, 0, tzinfo=timezone.utc).timestamp()


def _two_train_graph(gap_minutes: int = 60, h_min: float = 300.0) -> AlternativeGraph:
    """Two trains on one segment; alternative pair unresolved."""
    g = AlternativeGraph()
    g.t0_seconds = _t(6)
    g.commit_window_seconds = 600.0

    dep_a = EventNode("run-a", 1, "DEP")
    arr_a = EventNode("run-a", 2, "ARR")
    dep_b = EventNode("run-b", 1, "DEP")
    arr_b = EventNode("run-b", 2, "ARR")

    for node in (dep_a, arr_a, dep_b, arr_b):
        g.nodes.add(node)

    g.scheduled_times = {
        dep_a: _t(6),
        arr_a: _t(7),
        dep_b: _t(6) + gap_minutes * 60,
        arr_b: _t(7) + gap_minutes * 60,
    }
    g.station_for = {dep_a: "S1", arr_a: "S2", dep_b: "S1", arr_b: "S2"}

    for node, ts in g.scheduled_times.items():
        g.fixed_arcs.append(Arc(SOURCE, node, ts - g.t0_seconds))
    g.fixed_arcs.append(Arc(dep_a, arr_a, 3600.0))
    g.fixed_arcs.append(Arc(dep_b, arr_b, 3600.0))

    pair_id = "pair-1"
    g.alt_pairs[pair_id] = AltPair(
        pair_id=pair_id, edge_id=1,
        run_i="run-a", dep_stop_i=1, arr_stop_i=2,
        run_j="run-b", dep_stop_j=1, arr_stop_j=2,
        fwd=Arc(arr_a, dep_b, h_min),
        bwd=Arc(arr_b, dep_a, h_min),
    )
    g.selections[pair_id] = None
    return g


# ─────────────────────────────────────────────────────────────────────────────

def test_greedy_resolves_all_pairs():
    """GreedyPolicy must return a plan with no unresolved pairs."""
    g = _two_train_graph(gap_minutes=60)
    policy = GreedyPolicy(shield=FeasibilityShield())
    plans = policy.propose(g)
    assert len(plans) == 1
    plan = plans[0]
    assert plan.alt_graph.unresolved_pairs() == [], (
        "Greedy must resolve all pairs"
    )


def test_greedy_picks_natural_order():
    """With a 60-min gap, run-a (earlier) should be scheduled before run-b."""
    g = _two_train_graph(gap_minutes=60)
    policy = GreedyPolicy(shield=FeasibilityShield())
    plans = policy.propose(g)
    sel = plans[0].alt_graph.selections["pair-1"]
    # Direction 0 = run_i (run-a) first; direction 1 = run_j (run-b) first
    # run-a departs at 06:00, run-b at 07:00 → natural order is run-a first
    assert sel == 0, f"Expected direction 0 (run-a first), got {sel}"


def test_greedy_returns_candidate_plan():
    """Plan must have correct policy_name and a non-negative lower bound."""
    g = _two_train_graph(gap_minutes=60)
    policy = GreedyPolicy(shield=FeasibilityShield())
    plans = policy.propose(g)
    plan = plans[0]
    assert plan.policy_name == "greedy"
    assert plan.lower_bound >= 0.0


def test_greedy_warm_start_preserved():
    """Warm-start selections should be preserved if they pass the shield."""
    g = _two_train_graph(gap_minutes=60)
    warm = {"pair-1": 0}
    policy = GreedyPolicy(shield=FeasibilityShield())
    plans = policy.propose(g, warm_start=warm)
    assert plans[0].alt_graph.selections["pair-1"] == 0


def test_greedy_with_demo_data(app, _setup_demo_data):
    """GreedyPolicy must resolve all pairs in the demo snapshot."""
    with app.app_context():
        from services.snapshot_service import SnapshotService
        from rescheduling.alternative_graph import AlternativeGraph

        t0 = datetime(2026, 6, 13, 5, 0, 0, tzinfo=timezone.utc)
        snap = SnapshotService(horizon_minutes=600).build(t0=t0, trigger_type="test")
        run_ids = {r["run_id"] for r in snap.snapshot_json["runs"]}

        g = AlternativeGraph.build(
            snapshot_json=snap.snapshot_json,
            impact_run_ids=run_ids,
            t0=t0,
        )

        policy = GreedyPolicy(shield=FeasibilityShield())
        plans = policy.propose(g)

        assert len(plans) == 1
        assert plans[0].alt_graph.unresolved_pairs() == []
