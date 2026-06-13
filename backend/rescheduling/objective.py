"""
rescheduling/objective.py — Rail-Flow AI

ObjectiveFunction implements J_det as defined in Section 7 of the algorithm
report:

    J_det = L_sum + λ_max · L_max + λ_chg · N_chg + λ_hold · H_add

Default weights (PDF Table 2):
  λ_max  = 0.25   (dimensionless — scales the max single-train delay seconds)
  λ_chg  = 60     (seconds penalty per changed train)
  λ_hold = 10     (seconds penalty per additional hold-second)
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ScheduleMetrics:
    """
    Scalar inputs for the objective function.  All times in seconds.

    :param L_sum:  Sum of terminal delays across all trains in the impact zone.
    :param L_max:  Maximum terminal delay among any single train.
    :param N_chg:  Count of trains whose total added hold differs from the
                   baseline by at least one "change threshold" (default 60 s).
    :param H_add:  Total additional hold-seconds added across all stops
                   (i.e. sum of positive deviations from the baseline holds).
    """
    L_sum: float
    L_max: float
    N_chg: int
    H_add: float


class ObjectiveFunction:
    """
    Compute J_det and the risk-adjusted J_risk for a candidate schedule.

    Usage::

        obj = ObjectiveFunction()
        score = obj.score(metrics)

        # With risk term (Phase 7):
        # J_risk = J_det + λ_risk · CVaR_α
        # obj.risk_score(metrics, cvar_value) -> float
    """

    def __init__(
        self,
        lambda_max: float = 0.25,
        lambda_chg: float = 60.0,
        lambda_hold: float = 10.0,
        lambda_risk: float = 0.25,
        change_threshold_seconds: float = 60.0,
    ) -> None:
        self.lambda_max = lambda_max
        self.lambda_chg = lambda_chg
        self.lambda_hold = lambda_hold
        self.lambda_risk = lambda_risk
        self.change_threshold_seconds = change_threshold_seconds

    def score(self, metrics: ScheduleMetrics) -> float:
        """
        Return J_det for the given schedule metrics.

        All components are non-negative; a lower value is better.
        """
        return (
            metrics.L_sum
            + self.lambda_max * metrics.L_max
            + self.lambda_chg * metrics.N_chg
            + self.lambda_hold * metrics.H_add
        )

    def risk_score(self, metrics: ScheduleMetrics, cvar: float) -> float:
        """
        Return J_risk = J_det + λ_risk · CVaR_α.
        Used by ScenarioEvaluator in Phase 7.
        """
        return self.score(metrics) + self.lambda_risk * cvar

    # ------------------------------------------------------------------
    # Metric computation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def compute_metrics(
        terminal_delays: dict[str, float],
        baseline_terminal_delays: dict[str, float],
        added_holds: dict[tuple[str, int], float],
        baseline_holds: dict[tuple[str, int], float],
        change_threshold_seconds: float = 60.0,
    ) -> ScheduleMetrics:
        """
        Compute :class:`ScheduleMetrics` from raw simulation outputs.

        :param terminal_delays:  run_id -> delay in seconds (from EventSimulator).
        :param baseline_terminal_delays:  Same structure for the baseline schedule.
        :param added_holds:      (run_id, stop_seq) -> added hold seconds in candidate.
        :param baseline_holds:   Same structure for the baseline schedule.
        :param change_threshold_seconds: Minimum hold change to count as N_chg.
        """
        L_sum = sum(terminal_delays.values())
        L_max = max(terminal_delays.values(), default=0.0)

        N_chg = 0
        for run_id, delay in terminal_delays.items():
            base_delay = baseline_terminal_delays.get(run_id, 0.0)
            # A train "changed" if its total added hold at any stop differs
            # from baseline by >= change_threshold_seconds.
            run_added = sum(
                v for (rid, _), v in added_holds.items() if rid == run_id
            )
            run_base = sum(
                v for (rid, _), v in baseline_holds.items() if rid == run_id
            )
            if abs(run_added - run_base) >= change_threshold_seconds:
                N_chg += 1

        H_add = sum(
            max(
                added_holds.get(k, 0.0) - baseline_holds.get(k, 0.0),
                0.0,
            )
            for k in set(added_holds) | set(baseline_holds)
        )

        return ScheduleMetrics(L_sum=L_sum, L_max=L_max, N_chg=N_chg, H_add=H_add)
