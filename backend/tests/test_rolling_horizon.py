"""
test_rolling_horizon.py — Integration tests for RollingHorizonService (Phase 7).

All tests require a Flask application context and demo data.
No background threads are started — run_cycle is called synchronously.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

_T0 = datetime(2026, 6, 13, 5, 0, 0, tzinfo=timezone.utc)


# ─────────────────────────────────────────────────────────────────────────────
# Single cycle
# ─────────────────────────────────────────────────────────────────────────────

def test_run_cycle_returns_rescheduling_run(app, _setup_demo_data):
    """run_cycle returns a ReschedulingRun ORM row, not None."""
    with app.app_context():
        from models import ReschedulingRun
        from rescheduling.rolling_horizon import RollingHorizonService

        svc = RollingHorizonService(horizon_minutes=600)
        rr = svc.run_cycle(_T0)

        assert rr is not None
        assert isinstance(rr, ReschedulingRun)
        assert rr.rescheduling_run_id is not None


def test_run_cycle_sets_status(app, _setup_demo_data):
    """Status field is 'success' or 'partial' (never None or empty)."""
    with app.app_context():
        from rescheduling.rolling_horizon import RollingHorizonService

        svc = RollingHorizonService(horizon_minutes=600)
        rr = svc.run_cycle(_T0)

        assert rr is not None
        assert rr.status in ("success", "partial")


def test_run_cycle_records_policy_name(app, _setup_demo_data):
    """Policy name is recorded in the ReschedulingRun row."""
    with app.app_context():
        from rescheduling.rolling_horizon import RollingHorizonService

        svc = RollingHorizonService(horizon_minutes=600, policy_name="greedy")
        rr = svc.run_cycle(_T0)

        assert rr is not None
        assert rr.policy_name == "greedy"


# ─────────────────────────────────────────────────────────────────────────────
# Warm start
# ─────────────────────────────────────────────────────────────────────────────

def test_warm_arc_selection_populated_after_first_cycle(app, _setup_demo_data):
    """_warm_arc_selection is a dict after the first cycle."""
    with app.app_context():
        from rescheduling.rolling_horizon import RollingHorizonService

        svc = RollingHorizonService(horizon_minutes=600)
        assert svc._warm_arc_selection is None

        svc.run_cycle(_T0)

        assert svc._warm_arc_selection is not None
        assert isinstance(svc._warm_arc_selection, dict)


def test_second_cycle_succeeds_with_warm_start(app, _setup_demo_data):
    """Two consecutive cycles both return valid ReschedulingRun rows."""
    with app.app_context():
        from models import ReschedulingRun
        from rescheduling.rolling_horizon import RollingHorizonService

        svc = RollingHorizonService(horizon_minutes=600)
        rr1 = svc.run_cycle(_T0)
        rr2 = svc.run_cycle(_T0)

        assert isinstance(rr1, ReschedulingRun)
        assert isinstance(rr2, ReschedulingRun)
        assert rr1.rescheduling_run_id != rr2.rescheduling_run_id


def test_warm_start_does_not_change_objective_on_identical_input(app, _setup_demo_data):
    """
    When the network state is identical, warm start should not make the
    objective worse than the cold-start result.
    """
    with app.app_context():
        from rescheduling.rolling_horizon import RollingHorizonService

        svc = RollingHorizonService(horizon_minutes=600)
        rr1 = svc.run_cycle(_T0)     # cold start
        rr2 = svc.run_cycle(_T0)     # warm start

        assert rr1 is not None and rr2 is not None
        obj_cold = rr1.objective_after or 0.0
        obj_warm = rr2.objective_after or 0.0

        # Warm start should not be strictly worse by more than 1 % tolerance
        assert obj_warm <= obj_cold * 1.01 + 1.0, (
            f"Warm-start objective {obj_warm} is much worse than cold-start {obj_cold}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Policy and prediction flags
# ─────────────────────────────────────────────────────────────────────────────

def test_greedy_policy_variant(app, _setup_demo_data):
    """RollingHorizonService can be configured with greedy policy."""
    with app.app_context():
        from rescheduling.rolling_horizon import RollingHorizonService

        svc = RollingHorizonService(horizon_minutes=600, policy_name="greedy")
        rr = svc.run_cycle(_T0)

        assert rr is not None
        assert rr.policy_name == "greedy"


def test_no_predictions_variant(app, _setup_demo_data):
    """run_cycle succeeds when use_predictions=False."""
    with app.app_context():
        from rescheduling.rolling_horizon import RollingHorizonService

        svc = RollingHorizonService(horizon_minutes=600, use_predictions=False)
        rr = svc.run_cycle(_T0)

        assert rr is not None
        assert rr.predictor_name == "none"


# ─────────────────────────────────────────────────────────────────────────────
# stop() does not raise
# ─────────────────────────────────────────────────────────────────────────────

def test_stop_without_worker_does_not_raise():
    """Calling stop() before start_background_worker() must not raise."""
    from rescheduling.rolling_horizon import RollingHorizonService

    svc = RollingHorizonService()
    svc.stop()  # must not raise
