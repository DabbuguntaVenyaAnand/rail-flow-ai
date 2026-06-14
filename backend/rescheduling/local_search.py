"""
rescheduling/local_search.py — Rail-Flow AI

LocalSearch: Section 8.5 of the HSR-RailFlow report.

Three non-worsening move types applied until the time budget is exhausted:
  1. FlipPrecedence(pair_id)           — swap arc direction for one pair
  2. RemoveHold(run_id, dep_stop_seq)  — zero a release-arc extension
  3. ShortenHold(run_id, dep_stop_seq, delta) — reduce hold by delta seconds

A move is accepted only if the full FeasibilityShield passes and the objective
does not increase.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

from rescheduling.alternative_graph import AlternativeGraph, AltPair, EventNode, SOURCE, Arc
from rescheduling.feasibility import FeasibilityShield

SHORTEN_DELTAS = (30.0, 60.0, 120.0, 300.0)   # seconds


@dataclass
class CandidatePlan:
    """Output of a policy invocation."""
    alt_graph: AlternativeGraph
    holds: dict                    # {(run_id, stop_seq): hold_seconds}
    lower_bound: float
    policy_name: str = "unknown"


class LocalSearch:
    """
    Apply non-worsening local search moves to a CandidatePlan.

    Usage::

        ls = LocalSearch(shield, time_limit_ms=500)
        improved = ls.improve(plan)
    """

    def __init__(
        self,
        shield: Optional[FeasibilityShield] = None,
        time_limit_ms: int = 500,
        lambda_max: float = 0.25,
        lambda_chg: float = 60.0,
        lambda_hold: float = 10.0,
    ) -> None:
        self.shield = shield or FeasibilityShield(lambda_max, lambda_chg, lambda_hold)
        self.time_limit_ms = time_limit_ms
        self.lambda_max = lambda_max
        self.lambda_chg = lambda_chg
        self.lambda_hold = lambda_hold

    def improve(self, plan: CandidatePlan) -> CandidatePlan:
        """
        Iterate over all move types until no improvement is found or time runs out.
        Returns the best plan found (which may be the same as the input).
        """
        deadline = time.monotonic() + self.time_limit_ms / 1000.0
        current = plan
        improved = True

        while improved and time.monotonic() < deadline:
            improved = False
            g = current.alt_graph

            # Move 1: FlipPrecedence
            for pair in list(g.alt_pairs.values()):
                if time.monotonic() > deadline:
                    break
                current_sel = g.selections.get(pair.pair_id)
                if current_sel is None:
                    continue
                flipped_dir = 1 - current_sel
                candidate = g.copy()
                candidate.select_arc(pair.pair_id, flipped_dir)
                result = self.shield.validate(candidate)
                if result.accepted and result.lower_bound <= current.lower_bound + 1.0:
                    current = CandidatePlan(
                        alt_graph=candidate,
                        holds=dict(current.holds),
                        lower_bound=result.lower_bound,
                        policy_name=current.policy_name,
                    )
                    improved = True
                    break

            # Move 2: RemoveHold — zero a release-arc extension
            for (run_id, stop_seq), hold_val in list(current.holds.items()):
                if time.monotonic() > deadline:
                    break
                if hold_val <= 0:
                    continue
                candidate = current.alt_graph.copy()
                dep_node = EventNode(run_id, stop_seq, "DEP")
                # Restore release arc to original scheduled offset
                sched_ts = current.alt_graph.scheduled_times.get(dep_node)
                if sched_ts is None:
                    continue
                orig_weight = max(0.0, sched_ts - current.alt_graph.t0_seconds)
                candidate.fixed_arcs = [
                    arc for arc in candidate.fixed_arcs
                    if not (arc.src == SOURCE and arc.dst == dep_node)
                ]
                candidate.fixed_arcs.append(Arc(SOURCE, dep_node, orig_weight))
                result = self.shield.validate(candidate)
                if result.accepted and result.lower_bound <= current.lower_bound + 1.0:
                    new_holds = dict(current.holds)
                    new_holds[(run_id, stop_seq)] = 0.0
                    current = CandidatePlan(
                        alt_graph=candidate,
                        holds=new_holds,
                        lower_bound=result.lower_bound,
                        policy_name=current.policy_name,
                    )
                    improved = True
                    break

            # Move 3: ShortenHold — reduce a hold by delta
            for (run_id, stop_seq), hold_val in list(current.holds.items()):
                if time.monotonic() > deadline:
                    break
                if hold_val <= 0:
                    continue
                for delta in SHORTEN_DELTAS:
                    new_hold = max(0.0, hold_val - delta)
                    candidate = current.alt_graph.copy()
                    dep_node = EventNode(run_id, stop_seq, "DEP")
                    sched_ts = current.alt_graph.scheduled_times.get(dep_node)
                    if sched_ts is None:
                        continue
                    new_floor = max(0.0, sched_ts - current.alt_graph.t0_seconds + new_hold)
                    candidate.fixed_arcs = [
                        arc for arc in candidate.fixed_arcs
                        if not (arc.src == SOURCE and arc.dst == dep_node)
                    ]
                    candidate.fixed_arcs.append(Arc(SOURCE, dep_node, new_floor))
                    result = self.shield.validate(candidate)
                    if result.accepted and result.lower_bound <= current.lower_bound + 1.0:
                        new_holds = dict(current.holds)
                        new_holds[(run_id, stop_seq)] = new_hold
                        current = CandidatePlan(
                            alt_graph=candidate,
                            holds=new_holds,
                            lower_bound=result.lower_bound,
                            policy_name=current.policy_name,
                        )
                        improved = True
                        break
                if improved:
                    break

        return current


def _timetable_order(pair: AltPair, g: AlternativeGraph) -> Optional[int]:
    """
    Return the timetable-natural ordering direction for a pair:
    0 if run_i is scheduled before run_j on the segment, 1 otherwise.
    """
    dep_i = EventNode(pair.run_i, pair.dep_stop_i, "DEP")
    dep_j = EventNode(pair.run_j, pair.dep_stop_j, "DEP")
    sched_i = g.scheduled_times.get(dep_i)
    sched_j = g.scheduled_times.get(dep_j)
    if sched_i is None or sched_j is None:
        return None
    return 0 if sched_i <= sched_j else 1
