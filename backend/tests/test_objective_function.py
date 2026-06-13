"""
test_objective_function.py — Unit tests for ObjectiveFunction and ScheduleMetrics.

All tests use hand-computed expected values so regressions are immediately
obvious without understanding the rest of the system.
"""

import pytest
from rescheduling.objective import ObjectiveFunction, ScheduleMetrics


# Default weights (from PDF Table 2):
#   lambda_max  = 0.25
#   lambda_chg  = 60
#   lambda_hold = 10

def _make_obj(**kwargs) -> ObjectiveFunction:
    return ObjectiveFunction(**kwargs)


def _make_metrics(**kwargs) -> ScheduleMetrics:
    defaults = {"L_sum": 0.0, "L_max": 0.0, "N_chg": 0, "H_add": 0.0}
    defaults.update(kwargs)
    return ScheduleMetrics(**defaults)


# ---------------------------------------------------------------------------
# ObjectiveFunction.score() — hand-computed reference values
# ---------------------------------------------------------------------------

def test_score_zero_when_all_zero():
    obj = ObjectiveFunction()
    m = _make_metrics()
    assert obj.score(m) == 0.0


def test_score_l_sum_only():
    """J = L_sum when all other metrics are 0."""
    obj = ObjectiveFunction()
    m = _make_metrics(L_sum=300.0)
    assert obj.score(m) == 300.0


def test_score_l_max_scaled():
    """J = lambda_max * L_max = 0.25 * 400 = 100."""
    obj = ObjectiveFunction(lambda_max=0.25)
    m = _make_metrics(L_max=400.0)
    assert obj.score(m) == pytest.approx(100.0)


def test_score_n_chg_penalty():
    """Each changed train costs lambda_chg = 60 seconds."""
    obj = ObjectiveFunction(lambda_chg=60.0)
    m = _make_metrics(N_chg=3)
    assert obj.score(m) == pytest.approx(180.0)


def test_score_h_add_penalty():
    """Each additional hold-second costs lambda_hold = 10."""
    obj = ObjectiveFunction(lambda_hold=10.0)
    m = _make_metrics(H_add=5.0)
    assert obj.score(m) == pytest.approx(50.0)


def test_score_combined():
    """
    Combined test:
      L_sum=600, L_max=200, N_chg=2, H_add=30
      J = 600 + 0.25*200 + 60*2 + 10*30
        = 600 + 50 + 120 + 300
        = 1070
    """
    obj = ObjectiveFunction(
        lambda_max=0.25, lambda_chg=60.0, lambda_hold=10.0
    )
    m = _make_metrics(L_sum=600.0, L_max=200.0, N_chg=2, H_add=30.0)
    assert obj.score(m) == pytest.approx(1070.0)


def test_score_lower_is_better():
    """A schedule with less delay should score lower than one with more."""
    obj = ObjectiveFunction()
    better = _make_metrics(L_sum=100.0, L_max=50.0, N_chg=0, H_add=0.0)
    worse  = _make_metrics(L_sum=500.0, L_max=200.0, N_chg=2, H_add=10.0)
    assert obj.score(better) < obj.score(worse)


# ---------------------------------------------------------------------------
# ObjectiveFunction.risk_score()
# ---------------------------------------------------------------------------

def test_risk_score_adds_cvar():
    """
    J_risk = J_det + lambda_risk * cvar
    With J_det=100, lambda_risk=0.25, cvar=200:
    J_risk = 100 + 0.25*200 = 150
    """
    obj = ObjectiveFunction(lambda_risk=0.25)
    m = _make_metrics(L_sum=100.0)
    assert obj.risk_score(m, cvar=200.0) == pytest.approx(150.0)


def test_risk_score_equals_score_when_cvar_zero():
    obj = ObjectiveFunction()
    m = _make_metrics(L_sum=300.0, L_max=100.0, N_chg=1)
    assert obj.risk_score(m, cvar=0.0) == pytest.approx(obj.score(m))


# ---------------------------------------------------------------------------
# ObjectiveFunction.compute_metrics() helper
# ---------------------------------------------------------------------------

def test_compute_metrics_l_sum_and_l_max():
    terminal_delays = {"r1": 300.0, "r2": 600.0, "r3": 0.0}
    baseline = {"r1": 0.0, "r2": 0.0, "r3": 0.0}
    added = {}
    baseline_holds = {}

    m = ObjectiveFunction.compute_metrics(
        terminal_delays, baseline, added, baseline_holds
    )
    assert m.L_sum == pytest.approx(900.0)
    assert m.L_max == pytest.approx(600.0)


def test_compute_metrics_n_chg_counts_trains_with_changed_holds():
    """
    A train is counted in N_chg when its total added hold changes by >= 60 s.
    Train r1 gains 120 s hold (>= 60 s threshold) -> N_chg includes r1.
    Train r2 gains 30 s hold (< 60 s threshold)  -> not counted.
    """
    terminal_delays = {"r1": 0.0, "r2": 0.0}
    baseline = {"r1": 0.0, "r2": 0.0}
    added    = {("r1", 1): 120.0, ("r2", 1): 30.0}
    base_h   = {("r1", 1): 0.0,   ("r2", 1): 0.0}

    m = ObjectiveFunction.compute_metrics(
        terminal_delays, baseline, added, base_h
    )
    assert m.N_chg == 1


def test_compute_metrics_h_add_is_positive_hold_increase():
    """
    H_add counts only positive deviations from baseline.
    r1: added 200 s, baseline 50 s  -> +150 s
    r2: added 20 s, baseline 80 s   -> no increase (negative deviation ignored)
    """
    terminal_delays = {"r1": 0.0, "r2": 0.0}
    baseline = {"r1": 0.0, "r2": 0.0}
    added  = {("r1", 1): 200.0, ("r2", 1): 20.0}
    base_h = {("r1", 1): 50.0,  ("r2", 1): 80.0}

    m = ObjectiveFunction.compute_metrics(
        terminal_delays, baseline, added, base_h
    )
    assert m.H_add == pytest.approx(150.0)


# ---------------------------------------------------------------------------
# EventSimulator basic sanity
# ---------------------------------------------------------------------------

def test_event_simulator_propagates_delay():
    """
    A hold at stop 1 should push downstream arrival at stop 2 by the same amount.
    """
    from datetime import datetime, timezone, timedelta
    from simulator.event_simulator import EventSimulator, ScheduledStop

    base = datetime(2026, 6, 13, 6, 0, 0, tzinfo=timezone.utc)
    stops = [
        ScheduledStop(
            run_id="r1", stop_sequence=1, station_code="A",
            scheduled_arrival=None,
            scheduled_departure=base,
            min_dwell_seconds=0,
        ),
        ScheduledStop(
            run_id="r1", stop_sequence=2, station_code="B",
            scheduled_arrival=base + timedelta(hours=1),
            scheduled_departure=base + timedelta(hours=1),
            min_dwell_seconds=0,
        ),
    ]

    sim = EventSimulator()
    # Add 300 s hold at stop 1
    result = sim.materialise(stops, holds={("r1", 1): 300.0})

    from simulator.event_simulator import EventKey
    dep_stop1 = result.events[EventKey("r1", 1, "DEP")]
    arr_stop2 = result.events[EventKey("r1", 2, "ARR")]

    # Departure at stop 1 should be pushed 300 s later
    expected_dep = base + timedelta(seconds=300)
    assert dep_stop1.time == expected_dep

    # Arrival at stop 2 should also be pushed by 300 s (running time preserved)
    expected_arr2 = base + timedelta(hours=1, seconds=300)
    assert arr_stop2.time == expected_arr2


def test_event_simulator_terminal_delay():
    """Terminal delay at the last stop should match the hold applied."""
    from datetime import datetime, timezone, timedelta
    from simulator.event_simulator import EventSimulator, ScheduledStop

    base = datetime(2026, 6, 13, 6, 0, 0, tzinfo=timezone.utc)
    stops = [
        ScheduledStop(
            run_id="r1", stop_sequence=1, station_code="A",
            scheduled_arrival=None,
            scheduled_departure=base,
            min_dwell_seconds=0,
        ),
        ScheduledStop(
            run_id="r1", stop_sequence=2, station_code="B",
            scheduled_arrival=base + timedelta(hours=2),
            scheduled_departure=base + timedelta(hours=2),
            min_dwell_seconds=0,
        ),
    ]

    sim = EventSimulator()
    result = sim.materialise(stops, holds={("r1", 1): 600.0})

    assert "r1" in result.terminal_delays
    assert result.terminal_delays["r1"] == pytest.approx(600.0)
