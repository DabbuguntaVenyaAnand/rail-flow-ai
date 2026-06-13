"""
test_beam_search_policy.py — Unit tests for BeamSearchPolicy (Algorithm 5).
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
from policies.greedy_policy import GreedyPolicy
from policies.beam_search_policy import BeamSearchPolicy


def _t(h: int, m: int = 0) -> float:
    return datetime(2026, 6, 13, h, m, 0, tzinfo=timezone.utc).timestamp()


def _two_train_graph() -> AlternativeGraph:
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
        dep_a: _t(6),                  arr_a: _t(7),
        dep_b: _t(6) + 3600,           arr_b: _t(7) + 3600,
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
        fwd=Arc(arr_a, dep_b, 300.0),
        bwd=Arc(arr_b, dep_a, 300.0),
    )
    g.selections[pair_id] = None
    return g


# ─────────────────────────────────────────────────────────────────────────────

def test_beam_returns_at_least_one_plan():
    g = _two_train_graph()
    shield = FeasibilityShield()
    policy = BeamSearchPolicy(shield=shield, beam_width=4, expansions_max=50)
    plans = policy.propose(g)
    assert len(plans) >= 1


def test_beam_plans_have_no_unresolved_pairs():
    g = _two_train_graph()
    shield = FeasibilityShield()
    policy = BeamSearchPolicy(shield=shield, beam_width=4, expansions_max=50)
    plans = policy.propose(g)
    for plan in plans:
        assert plan.alt_graph.unresolved_pairs() == [], (
            "All beam plans must be fully resolved"
        )


def test_beam_best_le_greedy():
    """
    The best beam plan should have lower_bound <= greedy lower_bound.
    (Beam search explores more paths; it can only do at least as well.)
    """
    g = _two_train_graph()
    shield = FeasibilityShield()
    greedy = GreedyPolicy(shield=shield)
    beam = BeamSearchPolicy(shield=shield, greedy_seeder=greedy,
                            beam_width=4, expansions_max=50)

    greedy_plans = greedy.propose(g)
    beam_plans = beam.propose(g)

    greedy_lb = greedy_plans[0].lower_bound
    beam_lb = min(p.lower_bound for p in beam_plans)

    assert beam_lb <= greedy_lb + 1.0, (
        f"Beam LB {beam_lb} should be ≤ greedy LB {greedy_lb}"
    )


def test_beam_with_demo_data(app, _setup_demo_data):
    """BeamSearchPolicy must return complete plans for demo snapshot."""
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

        shield = FeasibilityShield()
        policy = BeamSearchPolicy(shield=shield, beam_width=4, expansions_max=100)
        plans = policy.propose(g)

        assert len(plans) >= 1
        best = min(plans, key=lambda p: p.lower_bound)
        assert best.alt_graph.unresolved_pairs() == []
