"""
policies/beam_search_policy.py — Rail-Flow AI

BeamSearchPolicy — Algorithm 5 from the HSR-RailFlow report.

B=20 beam width, E_max=200 max expansions, 800 ms time limit.
At each step, the earliest unresolved pair is expanded in both directions;
only candidates that pass validate_partial() (cycle check) are retained.
The beam is pruned to the top-B states by lower-bound after each expansion.
"""

from __future__ import annotations

from typing import Optional

from rescheduling.alternative_graph import AlternativeGraph, AltPair, EventNode
from rescheduling.feasibility import FeasibilityShield
from rescheduling.local_search import CandidatePlan
from policies.greedy_policy import _earliest_pair, GreedyPolicy

BEAM_WIDTH = 20
EXPANSIONS_MAX = 200


class BeamSearchPolicy:
    """
    Algorithm 5: beam search over the space of arc-selection sequences.

    Usage::

        policy = BeamSearchPolicy()
        plans  = policy.propose(alt_graph)
        best   = min(plans, key=lambda p: p.lower_bound)
    """

    def __init__(
        self,
        shield: Optional[FeasibilityShield] = None,
        greedy_seeder: Optional[GreedyPolicy] = None,
        beam_width: int = BEAM_WIDTH,
        expansions_max: int = EXPANSIONS_MAX,
    ) -> None:
        self.shield = shield or FeasibilityShield()
        self.greedy_seeder = greedy_seeder or GreedyPolicy(shield=self.shield)
        self.beam_width = beam_width
        self.expansions_max = expansions_max

    def propose(
        self,
        alt_graph: AlternativeGraph,
        warm_start: Optional[dict] = None,
    ) -> list[CandidatePlan]:
        """
        Return up to beam_width complete, shield-valid CandidatePlans.

        Falls back to the greedy seed if the beam yields no complete plans.
        """
        # Seed the beam with the greedy solution
        greedy_plans = self.greedy_seeder.propose(alt_graph, warm_start)
        greedy_seed = greedy_plans[0]

        # Beam: list of (AlternativeGraph, lower_bound)
        initial_result = self.shield.validate_partial(alt_graph.copy())
        beam: list[tuple[AlternativeGraph, float]] = [
            (alt_graph.copy(), initial_result.lower_bound)
        ]

        complete: list[CandidatePlan] = []
        expansions = 0

        while beam and expansions < self.expansions_max:
            next_beam: list[tuple[AlternativeGraph, float]] = []
            made_progress = False

            for state, _ in beam:
                unresolved = state.unresolved_pairs()
                if not unresolved:
                    # Complete state — run full validation
                    result = self.shield.validate(state)
                    if result.accepted:
                        complete.append(CandidatePlan(
                            alt_graph=state,
                            holds={},
                            lower_bound=result.lower_bound,
                            policy_name="beam_search",
                        ))
                    continue

                pair = _earliest_pair(unresolved, state)
                made_progress = True

                for direction in (0, 1):
                    child = state.copy()
                    child.select_arc(pair.pair_id, direction)
                    result = self.shield.validate_partial(child)
                    if result.accepted:
                        next_beam.append((child, result.lower_bound))
                    expansions += 1
                    if expansions >= self.expansions_max:
                        break
                if expansions >= self.expansions_max:
                    break

            if not made_progress:
                break

            # Prune beam to top-B by lower bound
            next_beam.sort(key=lambda x: x[1])
            beam = next_beam[: self.beam_width]

        # Drain any remaining complete states from the final beam
        for state, _ in beam:
            if not state.unresolved_pairs():
                result = self.shield.validate(state)
                if result.accepted:
                    complete.append(CandidatePlan(
                        alt_graph=state,
                        holds={},
                        lower_bound=result.lower_bound,
                        policy_name="beam_search",
                    ))

        # Ensure at least the greedy seed is included
        if not complete:
            complete.append(greedy_seed)

        return complete
