"""
test_scenario_evaluator.py — Unit tests for ScenarioEvaluator (Phase 7).

Pure arithmetic tests do not require a Flask app context.
Integration tests (score with demo data) use the shared session fixture.
"""

from __future__ import annotations

import math

import pytest

from predictors.residual_model import ResidualModel
from simulator.scenario_evaluator import ScenarioEvaluator


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _empty_snapshot(run_ids: list[str]) -> dict:
    return {
        "t0": "2026-06-13T05:00:00+00:00",
        "runs": [
            {
                "run_id": rid,
                "train_number": rid,
                "events": [],
            }
            for rid in run_ids
        ],
        "live_states": [],
        "disruptions": [],
    }


# ─────────────────────────────────────────────────────────────────────────────
# CVaR arithmetic (static method — no app context needed)
# ─────────────────────────────────────────────────────────────────────────────

def test_cvar_top_one():
    """alpha=0.75, K=4 → tail=ceil(0.25*4)=1 → CVaR = max score."""
    scores = [0.0, 100.0, 200.0, 300.0]   # already sorted
    cvar = ScenarioEvaluator._compute_cvar(scores, alpha=0.75)
    assert cvar == pytest.approx(300.0)


def test_cvar_top_two():
    """alpha=0.50, K=4 → tail=ceil(0.50*4)=2 → CVaR = mean([200, 300]) = 250."""
    scores = [0.0, 100.0, 200.0, 300.0]
    cvar = ScenarioEvaluator._compute_cvar(scores, alpha=0.50)
    assert cvar == pytest.approx(250.0)


def test_cvar_all_tail():
    """alpha=0.0 → tail=K → CVaR = mean of all scores."""
    scores = [10.0, 20.0, 30.0, 40.0]
    cvar = ScenarioEvaluator._compute_cvar(scores, alpha=0.0)
    assert cvar == pytest.approx(25.0)


def test_cvar_single_score():
    """K=1: CVaR = that score regardless of alpha."""
    cvar = ScenarioEvaluator._compute_cvar([42.0], alpha=0.90)
    assert cvar == pytest.approx(42.0)


def test_cvar_empty_returns_zero():
    cvar = ScenarioEvaluator._compute_cvar([], alpha=0.90)
    assert cvar == pytest.approx(0.0)


def test_cvar_all_equal():
    """When all scenarios score the same, CVaR = that score."""
    scores = [50.0] * 8
    cvar = ScenarioEvaluator._compute_cvar(scores, alpha=0.90)
    assert cvar == pytest.approx(50.0)


# ─────────────────────────────────────────────────────────────────────────────
# ScenarioEvaluator structure
# ─────────────────────────────────────────────────────────────────────────────

def test_evaluator_builds_train_number_lookup():
    snap = _empty_snapshot(["r1", "r2"])
    snap["runs"][0]["train_number"] = "12301"
    snap["runs"][1]["train_number"] = "12305"
    ev = ScenarioEvaluator(ResidualModel(), snap)
    assert ev._train_numbers["r1"] == "12301"
    assert ev._train_numbers["r2"] == "12305"


def test_evaluator_builds_last_station_lookup():
    snap = {
        "t0": "2026-06-13T05:00:00+00:00",
        "runs": [
            {
                "run_id": "r1",
                "train_number": "12301",
                "events": [
                    {"stop_sequence": 1, "station_code": "HWH"},
                    {"stop_sequence": 2, "station_code": "BWN"},
                ],
            }
        ],
        "live_states": [],
        "disruptions": [],
    }
    ev = ScenarioEvaluator(ResidualModel(), snap)
    assert ev._last_station["r1"] == "BWN"


# ─────────────────────────────────────────────────────────────────────────────
# Integration: score with demo data (requires app context)
# ─────────────────────────────────────────────────────────────────────────────

def test_score_returns_float_with_demo_data(app, _setup_demo_data):
    """score() returns a non-negative float for the greedy plan on demo data."""
    with app.app_context():
        from datetime import datetime, timezone

        from policies.greedy_policy import GreedyPolicy
        from rescheduling.alternative_graph import AlternativeGraph
        from rescheduling.feasibility import FeasibilityShield
        from services.snapshot_service import SnapshotService

        t0 = datetime(2026, 6, 13, 5, 0, 0, tzinfo=timezone.utc)
        snap = SnapshotService(horizon_minutes=600).build(t0=t0, trigger_type="test")
        snap_json = snap.snapshot_json

        all_run_ids = {r["run_id"] for r in snap_json.get("runs", [])}
        alt_graph = AlternativeGraph.build(
            snapshot_json=snap_json,
            impact_run_ids=all_run_ids,
            t0=t0,
            horizon_minutes=600,
        )

        shield = FeasibilityShield()
        plans = GreedyPolicy(shield=shield).propose(alt_graph)
        assert plans, "GreedyPolicy produced no plans on demo data"

        model = ResidualModel.build_from_snapshot(snap_json)
        evaluator = ScenarioEvaluator(model, snap_json, K=4, alpha=0.50)
        j_risk = evaluator.score(plans[0], horizon_minutes=30)

        assert isinstance(j_risk, float)
        assert j_risk >= 0.0


def test_zero_residuals_cvar_equals_jdet_scaled(app, _setup_demo_data):
    """
    With an empty ResidualModel (all residuals zero), every scenario produces
    the same score as J_det.  So CVaR = J_det and
    J_risk = J_det + lambda_risk * J_det = J_det * (1 + lambda_risk).
    """
    with app.app_context():
        from datetime import datetime, timezone

        from policies.greedy_policy import GreedyPolicy
        from rescheduling.alternative_graph import AlternativeGraph
        from rescheduling.feasibility import FeasibilityShield
        from rescheduling.objective import ObjectiveFunction, ScheduleMetrics
        from services.snapshot_service import SnapshotService

        t0 = datetime(2026, 6, 13, 5, 0, 0, tzinfo=timezone.utc)
        snap = SnapshotService(horizon_minutes=600).build(t0=t0, trigger_type="test")
        snap_json = snap.snapshot_json

        all_run_ids = {r["run_id"] for r in snap_json.get("runs", [])}
        alt_graph = AlternativeGraph.build(
            snapshot_json=snap_json,
            impact_run_ids=all_run_ids,
            t0=t0,
            horizon_minutes=600,
        )

        shield = FeasibilityShield()
        plans = GreedyPolicy(shield=shield).propose(alt_graph)
        plan = plans[0]

        obj_fn = ObjectiveFunction()
        model = ResidualModel()  # empty → all residuals = 0.0
        evaluator = ScenarioEvaluator(model, snap_json, obj_fn=obj_fn, K=4, alpha=0.50)
        j_risk = evaluator.score(plan, horizon_minutes=30)

        # J_det from base delays
        base_delays = evaluator._terminal_delays_from_plan(plan)
        n_chg = sum(1 for v in plan.holds.values() if v > 0)
        h_add = sum(max(0.0, v) for v in plan.holds.values())
        metrics = ScheduleMetrics(
            L_sum=sum(base_delays.values()),
            L_max=max(base_delays.values(), default=0.0),
            N_chg=n_chg,
            H_add=h_add,
        )
        j_det = obj_fn.score(metrics)
        expected = j_det + obj_fn.lambda_risk * j_det   # CVaR = J_det when residuals=0

        assert j_risk == pytest.approx(expected, rel=1e-6)
