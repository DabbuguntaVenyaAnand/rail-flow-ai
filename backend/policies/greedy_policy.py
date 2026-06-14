"""
policies/greedy_policy.py — Rail-Flow AI

GreedyPolicy — Algorithm 4 from the HSR-RailFlow report.

Resolves alternative arc pairs one at a time in descending impact-score order.
For each pair, tries both directions through FeasibilityShield and picks the
direction with the lower lower-bound; on ties (within 1 s) picks the direction
with less added hold time.  Falls back to HoldFallback when both directions fail.
"""

from __future__ import annotations

import time
from typing import Optional

from rescheduling.alternative_graph import AlternativeGraph, AltPair, EventNode
from rescheduling.feasibility import FeasibilityShield
from rescheduling.fallback import HoldFallback
from rescheduling.local_search import CandidatePlan

_DEFAULT_TIME_LIMIT_MS = 5_000


class GreedyPolicy:
    """
    Algorithm 4: earliest-conflict-first greedy arc selection.

    Usage::

        policy = GreedyPolicy()
        plans = policy.propose(alt_graph)
        best = min(plans, key=lambda p: p.lower_bound)
    """

    def __init__(
        self,
        shield: Optional[FeasibilityShield] = None,
        fallback: Optional[HoldFallback] = None,
        time_limit_ms: int = _DEFAULT_TIME_LIMIT_MS,
    ) -> None:
        self.shield = shield or FeasibilityShield()
        self.fallback = fallback or HoldFallback()
        self.time_limit_ms = time_limit_ms

    def propose(
        self,
        alt_graph: AlternativeGraph,
        warm_start: Optional[dict] = None,
    ) -> list[CandidatePlan]:
        """
        Produce one or more candidate plans.

        :param alt_graph: Starting alternative graph (will not be mutated).
        :param warm_start: Previous arc_selection() dict for warm start.
        :returns: A list containing exactly one greedy CandidatePlan.
        """
        g = alt_graph.copy()
        if warm_start:
            g.apply_warm_start(warm_start)

        holds: dict = {}
        deadline = time.monotonic() + self.time_limit_ms / 1000.0

        while True:
            unresolved = g.unresolved_pairs()
            if not unresolved:
                break
            if time.monotonic() > deadline:
                break

            pair = _highest_impact_pair(unresolved, g)

            # Try both directions; collect (direction, graph, lower_bound)
            cands: list[tuple[int, AlternativeGraph, float]] = []
            for direction in (0, 1):
                candidate = g.copy()
                candidate.select_arc(pair.pair_id, direction)
                result = self.shield.validate_partial(candidate)
                if result.accepted:
                    cands.append((direction, candidate, result.lower_bound))

            if cands:
                cands.sort(key=lambda x: x[2])
                # Tie-break: when both LBs are within 1 s, pick min added hold
                if len(cands) == 2 and abs(cands[0][2] - cands[1][2]) < 1.0:
                    h0 = _hold_added(cands[0][0], pair, g, self.shield)
                    h1 = _hold_added(cands[1][0], pair, g, self.shield)
                    g = cands[0][1] if h0 <= h1 else cands[1][1]
                else:
                    g = cands[0][1]
            else:
                # Both directions failed — apply hold and try again
                g = self.fallback.apply(g, pair)
                # Record the hold
                dep_i = EventNode(pair.run_i, pair.dep_stop_i, "DEP")
                dep_j = EventNode(pair.run_j, pair.dep_stop_j, "DEP")
                sched_i = g.scheduled_times.get(dep_i, 0.0)
                sched_j = g.scheduled_times.get(dep_j, 0.0)
                hold_target = dep_j if sched_j >= sched_i else dep_i
                holds[(hold_target.run_id, hold_target.stop_sequence)] = (
                    holds.get((hold_target.run_id, hold_target.stop_sequence), 0.0)
                    + self.fallback.hold_seconds
                )

        # Final full validation
        final = self.shield.validate(g)
        lb = final.lower_bound if final.accepted else float("inf")

        return [CandidatePlan(
            alt_graph=g,
            holds=holds,
            lower_bound=lb,
            policy_name="greedy",
        )]


def _earliest_pair(pairs: list[AltPair], g: AlternativeGraph) -> AltPair:
    """Return the pair whose earliest participant is scheduled first."""
    def _min_sched(pair: AltPair) -> float:
        dep_i = EventNode(pair.run_i, pair.dep_stop_i, "DEP")
        dep_j = EventNode(pair.run_j, pair.dep_stop_j, "DEP")
        t_i = g.scheduled_times.get(dep_i, float("inf"))
        t_j = g.scheduled_times.get(dep_j, float("inf"))
        return min(t_i, t_j)

    return min(pairs, key=_min_sched)


def _impact_score(pair: AltPair, g: AlternativeGraph) -> int:
    """Count downstream trains whose DEP is scheduled after both trains in this pair."""
    later_dep = max(
        g.scheduled_times.get(EventNode(pair.run_i, pair.dep_stop_i, "DEP"), 0.0),
        g.scheduled_times.get(EventNode(pair.run_j, pair.dep_stop_j, "DEP"), 0.0),
    )
    return sum(
        1
        for n, t in g.scheduled_times.items()
        if n.kind == "DEP"
        and t > later_dep
        and n.run_id not in (pair.run_i, pair.run_j)
    )


def _highest_impact_pair(pairs: list[AltPair], g: AlternativeGraph) -> AltPair:
    """Return the pair with the highest downstream impact score."""
    return max(pairs, key=lambda p: _impact_score(p, g))


def _hold_added(
    direction: int,
    pair: AltPair,
    g: AlternativeGraph,
    shield,
) -> float:
    """Return total added hold seconds across both trains when arc is selected."""
    candidate = g.copy()
    candidate.select_arc(pair.pair_id, direction)
    result = shield.validate_partial(candidate)
    if not result.accepted:
        return float("inf")
    total = 0.0
    for node in (
        EventNode(pair.run_i, pair.dep_stop_i, "DEP"),
        EventNode(pair.run_j, pair.dep_stop_j, "DEP"),
    ):
        sched = g.scheduled_times.get(node, 0.0)
        actual = result.event_times.get(node, sched)
        total += max(0.0, actual - sched)
    return total
