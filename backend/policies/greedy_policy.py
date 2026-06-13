"""
policies/greedy_policy.py — Rail-Flow AI

GreedyPolicy — Algorithm 4 from the HSR-RailFlow report.

Resolves alternative arc pairs one at a time in earliest-scheduled-event order.
For each pair, tries both directions through FeasibilityShield and picks the
direction with the lower lower-bound.  Falls back to HoldFallback when both
directions fail.
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

            pair = _earliest_pair(unresolved, g)

            best_graph: Optional[AlternativeGraph] = None
            best_lb = float("inf")

            for direction in (0, 1):
                candidate = g.copy()
                candidate.select_arc(pair.pair_id, direction)
                result = self.shield.validate_partial(candidate)
                if result.accepted and result.lower_bound < best_lb:
                    best_lb = result.lower_bound
                    best_graph = candidate

            if best_graph is not None:
                g = best_graph
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
