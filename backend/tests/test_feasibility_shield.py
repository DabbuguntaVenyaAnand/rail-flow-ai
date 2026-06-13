"""
test_feasibility_shield.py — Unit tests for FeasibilityShield (Algorithm 3).

All tests use hand-built AlternativeGraph instances; no DB required for
the pure logic tests.
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
from rescheduling.feasibility import FeasibilityShield, _has_cycle, _longest_paths


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _t(h: int, m: int = 0) -> float:
    """Return Unix timestamp for 2026-06-13 HH:MM UTC."""
    return datetime(2026, 6, 13, h, m, 0, tzinfo=timezone.utc).timestamp()


def _two_train_graph(
    gap_minutes: int = 60,
    h_min: float = 300.0,
    select: int = 0,
) -> AlternativeGraph:
    """
    Two trains on one segment separated by gap_minutes.
    'select' sets the initial direction (None = unresolved).
    """
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
    if select is not None:
        g.selections[pair_id] = select
    else:
        g.selections[pair_id] = None

    return g


# ─────────────────────────────────────────────────────────────────────────────
# Stage 1: Cycle detection
# ─────────────────────────────────────────────────────────────────────────────

def test_no_cycle_in_dag():
    n1 = EventNode("r", 1, "DEP")
    n2 = EventNode("r", 2, "ARR")
    arcs = [Arc(SOURCE, n1, 0), Arc(n1, n2, 100)]
    assert _has_cycle(arcs, {n1, n2}) is False


def test_cycle_detected():
    n1 = EventNode("r", 1, "DEP")
    n2 = EventNode("r", 2, "ARR")
    # n1 → n2 → n1 forms a cycle
    arcs = [Arc(n1, n2, 100), Arc(n2, n1, 100)]
    assert _has_cycle(arcs, {n1, n2}) is True


def test_self_loop_is_cycle():
    n1 = EventNode("r", 1, "DEP")
    arcs = [Arc(n1, n1, 0)]
    assert _has_cycle(arcs, {n1}) is True


# ─────────────────────────────────────────────────────────────────────────────
# Stage 2: Longest paths
# ─────────────────────────────────────────────────────────────────────────────

def test_longest_paths_single_chain():
    n1 = EventNode("r", 1, "DEP")
    n2 = EventNode("r", 2, "ARR")
    t0 = _t(6)
    arcs = [Arc(SOURCE, n1, 0), Arc(n1, n2, 3600)]
    lp = _longest_paths(arcs, {n1, n2}, t0)
    assert lp[n1] == pytest.approx(t0)
    assert lp[n2] == pytest.approx(t0 + 3600)


def test_longest_paths_max_wins():
    """If two paths lead to the same node, the longer one determines its time."""
    n1 = EventNode("r", 1, "DEP")
    n2 = EventNode("r", 2, "DEP")
    n3 = EventNode("r", 3, "ARR")
    t0 = _t(6)
    arcs = [
        Arc(SOURCE, n1, 0),
        Arc(SOURCE, n2, 1000),
        Arc(n1, n3, 3600),
        Arc(n2, n3, 100),    # shorter path, but n2 starts later
    ]
    lp = _longest_paths(arcs, {n1, n2, n3}, t0)
    # n1-path: t0 + 3600; n2-path: t0 + 1000 + 100 = t0 + 1100
    assert lp[n3] == pytest.approx(t0 + 3600)


# ─────────────────────────────────────────────────────────────────────────────
# FeasibilityShield.validate()
# ─────────────────────────────────────────────────────────────────────────────

def test_validate_accepts_well_separated_trains():
    """60-min gap ≫ 5-min headway: both directions should be feasible."""
    shield = FeasibilityShield()
    g = _two_train_graph(gap_minutes=60, h_min=300.0, select=0)
    result = shield.validate(g)
    assert result.accepted, result.reason
    assert result.lower_bound >= 0.0


def test_validate_partial_skips_deep_checks():
    """validate_partial accepts a graph with unresolved pairs."""
    shield = FeasibilityShield()
    g = _two_train_graph(gap_minutes=60, select=None)
    result = shield.validate_partial(g)
    assert result.accepted


def test_validate_rejects_cycle():
    """Selecting both fwd and bwd for different pairs can create cycles."""
    shield = FeasibilityShield()
    # Build a graph where selecting direction 0 creates a cycle
    n1 = EventNode("r", 1, "DEP")
    n2 = EventNode("r", 2, "ARR")
    n3 = EventNode("r", 3, "DEP")

    g = AlternativeGraph()
    g.t0_seconds = _t(6)
    g.commit_window_seconds = 600.0
    g.nodes = {n1, n2, n3}
    g.scheduled_times = {n1: _t(6), n2: _t(7), n3: _t(8)}
    g.station_for = {n1: "A", n2: "B", n3: "C"}

    # Fixed arcs that are fine on their own
    g.fixed_arcs = [
        Arc(SOURCE, n1, 0),
        Arc(SOURCE, n2, 3600),
        Arc(SOURCE, n3, 7200),
    ]

    # Alt pair: fwd creates cycle n2 → n1 (backwards in time)
    pair_id = "p1"
    g.alt_pairs[pair_id] = AltPair(
        pair_id=pair_id, edge_id=1,
        run_i="r", dep_stop_i=1, arr_stop_i=2,
        run_j="r", dep_stop_j=3, arr_stop_j=4,
        fwd=Arc(n2, n1, 0),    # n2 → n1: creates back-edge (n2 after n1)
        bwd=Arc(n3, n2, 0),
    )
    g.selections[pair_id] = 0   # select the fwd arc

    # Also add n1 → n2 fixed arc to complete the cycle: n1→n2 via fixed, n2→n1 via alt
    g.fixed_arcs.append(Arc(n1, n2, 3600))

    result = shield.validate(g)
    assert not result.accepted
    assert "cycle" in result.reason.lower() or "deadlock" in result.reason.lower()


def test_lower_bound_increases_with_delay():
    """A delayed schedule should produce a higher lower bound than the scheduled one."""
    shield = FeasibilityShield(lambda_max=0.25)

    # No-delay case
    g_ok = _two_train_graph(gap_minutes=60, select=0)
    r_ok = shield.validate_partial(g_ok)

    # Delay run-b by 3600 s via its release arc
    g_delayed = _two_train_graph(gap_minutes=60, select=0)
    dep_b = EventNode("run-b", 1, "DEP")
    arr_b = EventNode("run-b", 2, "ARR")
    g_delayed.fixed_arcs = [
        arc for arc in g_delayed.fixed_arcs
        if arc.dst not in (dep_b, arr_b) or arc.src != SOURCE
    ]
    # Push dep_b 3600 s late
    g_delayed.fixed_arcs.append(Arc(SOURCE, dep_b, 3600.0 + 0.0))
    g_delayed.fixed_arcs.append(Arc(SOURCE, arr_b, 7200.0 + 3600.0))

    r_delayed = shield.validate_partial(g_delayed)
    assert r_delayed.lower_bound >= r_ok.lower_bound
