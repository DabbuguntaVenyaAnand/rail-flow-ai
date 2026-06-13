"""
rescheduling/fallback.py — Rail-Flow AI

HoldFallback: when neither direction of an alternative arc pair passes the
FeasibilityShield, add a time-padding hold to the later-scheduled train so that
one direction becomes feasible on the next iteration.
"""

from __future__ import annotations

from rescheduling.alternative_graph import AlternativeGraph, AltPair, EventNode

HOLD_SECONDS = 300.0   # 5-minute hold added when greedy policy is stuck


class HoldFallback:
    """
    Apply a fixed hold to make a stuck ordering decision feasible.

    The hold is represented as a tighter release arc on the SOURCE → DEP node
    for the later-scheduled train.  After applying the hold, the caller should
    retry both directions through the FeasibilityShield.
    """

    def __init__(self, hold_seconds: float = HOLD_SECONDS) -> None:
        self.hold_seconds = hold_seconds

    def apply(self, g: AlternativeGraph, pair: AltPair) -> AlternativeGraph:
        """
        Return a new graph copy with the hold applied.

        The hold is added to the train whose first event (DEP at dep_stop) has
        the *later* scheduled time.  The release arc weight for that DEP node
        is extended by hold_seconds.
        """
        from rescheduling.alternative_graph import SOURCE, Arc

        g2 = g.copy()

        dep_i = EventNode(pair.run_i, pair.dep_stop_i, "DEP")
        dep_j = EventNode(pair.run_j, pair.dep_stop_j, "DEP")

        sched_i = g.scheduled_times.get(dep_i, 0.0)
        sched_j = g.scheduled_times.get(dep_j, 0.0)

        # Add hold to the later-scheduled train (it's the one causing the conflict)
        hold_target = dep_j if sched_j >= sched_i else dep_i
        new_floor = (g.scheduled_times.get(hold_target, 0.0)
                     - g.t0_seconds
                     + self.hold_seconds)

        # Replace or strengthen the release arc for hold_target
        kept = [
            arc for arc in g2.fixed_arcs
            if not (arc.src == SOURCE and arc.dst == hold_target)
        ]
        kept.append(Arc(SOURCE, hold_target, max(new_floor, 0.0)))
        g2.fixed_arcs = kept

        return g2
