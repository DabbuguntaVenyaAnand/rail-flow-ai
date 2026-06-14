"""
simulator/scenario_evaluator.py — Rail-Flow AI

ScenarioEvaluator implements Algorithm 6 from the HSR-RailFlow report:
K-scenario deterministic evaluation with CVaR risk measure.

    J_risk = J_det + λ_risk · CVaR_α

CVaR_α (Conditional Value-at-Risk at level α):
  mean of the top ceil((1-α)·K) scenario scores.

Default: K=16, α=0.90 → tail is top 2 of 16 scenarios.

Residuals are drawn from a ResidualModel (deterministic by scenario_index).
When the ResidualModel is empty (no historical data), CVaR = J_det and
J_risk = J_det · (1 + λ_risk).

Usage::

    evaluator = ScenarioEvaluator(residual_model, snapshot_json)
    j_risk = evaluator.score(plan, horizon_minutes=30)
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Optional

from rescheduling.alternative_graph import EventNode
from rescheduling.objective import ObjectiveFunction, ScheduleMetrics


class ScenarioEvaluator:
    """
    Score a CandidatePlan with risk-adjusted J_risk.

    :param residual_model: :class:`~predictors.residual_model.ResidualModel`
        instance pre-populated with residuals.
    :param snapshot_json: Snapshot dict from SnapshotService — used to map
        run_ids to train_numbers and last-stop station codes.
    :param obj_fn: :class:`ObjectiveFunction` to use.  Defaults to the
        standard weights (λ_max=0.25, λ_chg=60, λ_hold=10, λ_risk=0.25).
    :param K: Number of scenarios.
    :param alpha: CVaR confidence level.  0.90 → top 10% worst-case.
    """

    def __init__(
        self,
        residual_model,
        snapshot_json: dict,
        obj_fn: Optional[ObjectiveFunction] = None,
        K: int = 16,
        alpha: float = 0.90,
    ) -> None:
        self.residual_model = residual_model
        self.snapshot_json = snapshot_json
        self.obj_fn = obj_fn or ObjectiveFunction()
        self.K = K
        self.alpha = alpha

        # Derived lookup tables (built once from snapshot_json)
        self._train_numbers: dict[str, str] = {
            r["run_id"]: r.get("train_number", r["run_id"])
            for r in snapshot_json.get("runs", [])
        }
        self._last_station: dict[str, str] = self._build_last_station()

    # ─────────────────────────────────────────────────────────────────────────
    # Public scoring interface
    # ─────────────────────────────────────────────────────────────────────────

    def score(
        self,
        plan,
        horizon_minutes: int = 30,
    ) -> float:
        """
        Compute J_risk for a CandidatePlan.

        When SCENARIO_EVALUATION_ENABLED is False (default), returns J_det
        directly — no K-scenario CVaR is computed. Set the flag to True only
        when a populated ResidualModel with historical data is available.

        :param plan: :class:`~rescheduling.local_search.CandidatePlan`.
        :param horizon_minutes: Horizon used to look up residuals.
        :returns: J_risk scalar (lower is better).
        """
        # Check feature flag; default off when no historical residual data exists
        try:
            from flask import current_app
            scenario_enabled = current_app.config.get("SCENARIO_EVALUATION_ENABLED", False)
        except RuntimeError:
            scenario_enabled = False

        base_delays = self._terminal_delays_from_plan(plan)

        n_chg = sum(1 for v in plan.holds.values() if v > 0)
        h_add = sum(max(0.0, v) for v in plan.holds.values())

        base_metrics = ScheduleMetrics(
            L_sum=sum(base_delays.values()),
            L_max=max(base_delays.values(), default=0.0),
            N_chg=n_chg,
            H_add=h_add,
        )
        j_det = self.obj_fn.score(base_metrics)

        if not scenario_enabled:
            return j_det

        scenario_scores = self._run_scenarios(
            base_delays, base_metrics, horizon_minutes
        )
        scenario_scores.sort()

        cvar = self._compute_cvar(scenario_scores, self.alpha)
        return self.obj_fn.risk_score(base_metrics, cvar)

    # ─────────────────────────────────────────────────────────────────────────
    # Static helpers (independently testable)
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _compute_cvar(sorted_scores: list[float], alpha: float) -> float:
        """
        Return CVaR_α = mean of the top ceil((1-α)·K) sorted scores.

        :param sorted_scores: Scenario scores in ascending order.
        :param alpha: Confidence level (e.g. 0.90).
        :returns: CVaR value.  Returns the single worst score if K=1.
        """
        if not sorted_scores:
            return 0.0
        K = len(sorted_scores)
        tail_count = max(1, math.ceil((1 - alpha) * K))
        return sum(sorted_scores[-tail_count:]) / tail_count

    # ─────────────────────────────────────────────────────────────────────────
    # Internal helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _run_scenarios(
        self,
        base_delays: dict[str, float],
        base_metrics: ScheduleMetrics,
        horizon_minutes: int,
    ) -> list[float]:
        """Compute J_det for each of the K perturbed scenarios."""
        scores: list[float] = []
        for k in range(self.K):
            perturbed: dict[str, float] = {}
            for run_id, base_d in base_delays.items():
                train_num = self._train_numbers.get(run_id, run_id)
                station = self._last_station.get(run_id, "")
                residual = self.residual_model.sample(
                    station, train_num, horizon_minutes, k
                )
                perturbed[run_id] = max(0.0, base_d + residual)

            metrics = ScheduleMetrics(
                L_sum=sum(perturbed.values()),
                L_max=max(perturbed.values(), default=0.0),
                N_chg=base_metrics.N_chg,
                H_add=base_metrics.H_add,
            )
            scores.append(self.obj_fn.score(metrics))
        return scores

    def _terminal_delays_from_plan(self, plan) -> dict[str, float]:
        """
        Derive per-run terminal delays from a CandidatePlan.

        Runs FeasibilityShield.validate() to materialise event_times, then
        computes delay = actual_ts − scheduled_ts at the last stop.

        Falls back to distributing plan.lower_bound evenly when the shield
        cannot produce valid event_times (e.g. partial plan without all arcs).
        """
        from rescheduling.feasibility import FeasibilityShield

        shield = FeasibilityShield()
        result = shield.validate(plan.alt_graph)

        if result.accepted and result.event_times:
            return self._delays_from_event_times(result.event_times)

        # Fallback: distribute lower_bound equally across impact runs
        runs = self.snapshot_json.get("runs", [])
        if not runs:
            return {}
        avg = plan.lower_bound / len(runs)
        return {r["run_id"]: avg for r in runs}

    def _delays_from_event_times(
        self, event_times: dict[EventNode, float]
    ) -> dict[str, float]:
        """Compute terminal delay per run from shield event_times."""
        delays: dict[str, float] = {}
        for run in self.snapshot_json.get("runs", []):
            run_id = run["run_id"]
            events = sorted(run.get("events", []), key=lambda e: e["stop_sequence"])
            if not events:
                continue
            last_ev = events[-1]
            seq = last_ev["stop_sequence"]

            dep_node = EventNode(run_id, seq, "DEP")
            arr_node = EventNode(run_id, seq, "ARR")
            node = dep_node if dep_node in event_times else arr_node
            if node not in event_times:
                delays[run_id] = 0.0
                continue

            actual_ts = event_times[node]
            sched_str = last_ev.get("scheduled_departure") or last_ev.get("scheduled_arrival")
            if not sched_str:
                delays[run_id] = 0.0
                continue

            try:
                sched_ts = datetime.fromisoformat(sched_str).timestamp()
            except (ValueError, TypeError):
                delays[run_id] = 0.0
                continue

            delays[run_id] = max(0.0, actual_ts - sched_ts)
        return delays

    def _build_last_station(self) -> dict[str, str]:
        """Return {run_id: last_stop_station_code}."""
        result: dict[str, str] = {}
        for run in self.snapshot_json.get("runs", []):
            events = sorted(run.get("events", []), key=lambda e: e["stop_sequence"])
            if events:
                result[run["run_id"]] = events[-1].get("station_code", "")
        return result
