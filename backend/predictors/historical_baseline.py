"""
predictors/historical_baseline.py — Rail-Flow AI

HistoricalBaselinePredictor: deterministic rule-based delay predictor.

Algorithm:
  1. Base delay = delay_seconds from live_states (current observation).
     Fallback: average of (actual - scheduled) from TimetableEvent actuals.
  2. Peak-hour multiplier ×1.3 if t0 is in IST morning/evening peak
     (IST = UTC+5:30; peak IST 07:00–09:00 → UTC 01:30–03:30,
                        peak IST 17:00–19:00 → UTC 11:30–13:30).
  3. Short-headway multiplier ×1.2 if a preceding train departed from the
     same station within SHORT_HEADWAY_SECONDS (900 s = 15 min).
  4. p90 = p50 × 1.6 (fixed ratio, calibrated on Indian rail data).
  5. Returns the same estimate for all requested horizons (Phase 5 will
     refine horizon-dependent decay).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from predictors.base import DelayEstimate

MODEL_VERSION = "historical_baseline_v1"
P90_RATIO = 1.6
PEAK_MULTIPLIER = 1.3
SHORT_HEADWAY_MULTIPLIER = 1.2
SHORT_HEADWAY_SECONDS = 900.0   # 15 minutes

# IST peak windows expressed as (start_seconds_from_midnight_UTC,
#                                 end_seconds_from_midnight_UTC)
# IST morning peak 07:00–09:00 → UTC 01:30–03:30
# IST evening peak 17:00–19:00 → UTC 11:30–13:30
_PEAK_UTC_WINDOWS = [
    (1 * 3600 + 30 * 60, 3 * 3600 + 30 * 60),
    (11 * 3600 + 30 * 60, 13 * 3600 + 30 * 60),
]


class HistoricalBaselinePredictor:
    """
    Rule-based historical baseline predictor.

    Usage::

        predictor = HistoricalBaselinePredictor()
        estimates = predictor.predict(snapshot_json, horizons=[15, 30, 60])
    """

    MODEL_VERSION = MODEL_VERSION

    def predict(
        self,
        snapshot_json: dict,
        horizons: list[int],
    ) -> list[DelayEstimate]:
        """
        Return one DelayEstimate per (run_id, horizon) in snapshot_json.

        :param snapshot_json: snapshot_json dict from OperationalSnapshot.
        :param horizons: Look-ahead horizons in minutes.
        :returns: Flat list of DelayEstimate objects.
        """
        if not horizons:
            return []

        t0_str = snapshot_json.get("t0", "")
        t0 = _parse_dt(t0_str)
        peak_factor = _peak_factor(t0) if t0 else 1.0

        # Current delays from live states (most recent observation per run)
        live_delays: dict[str, float] = {}
        for ls in snapshot_json.get("live_states", []):
            run_id = ls.get("run_id", "")
            delay = float(ls.get("delay_seconds", 0) or 0)
            if run_id and (run_id not in live_delays or delay > live_delays[run_id]):
                live_delays[run_id] = delay

        # Fallback delays from TimetableEvent actuals (within snapshot)
        event_delays = _event_based_delays(snapshot_json)

        # Short-headway detection
        short_hw_runs = _detect_short_headway(snapshot_json)

        estimates: list[DelayEstimate] = []
        for run in snapshot_json.get("runs", []):
            run_id = run["run_id"]
            base = live_delays.get(run_id) if run_id in live_delays else event_delays.get(run_id, 0.0)
            base = max(0.0, base)

            factor = peak_factor
            if run_id in short_hw_runs:
                factor *= SHORT_HEADWAY_MULTIPLIER

            p50 = base * factor
            p90 = p50 * P90_RATIO

            for h in horizons:
                estimates.append(DelayEstimate(
                    run_id=run_id,
                    horizon_minutes=h,
                    p50_delay_seconds=round(p50),
                    p90_delay_seconds=round(p90),
                    model_version=MODEL_VERSION,
                ))

        return estimates


# ─────────────────────────────────────────────────────────────────────────────
# Private helpers
# ─────────────────────────────────────────────────────────────────────────────

def _parse_dt(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None


def _parse_ts(s: Optional[str]) -> Optional[float]:
    dt = _parse_dt(s)
    return dt.timestamp() if dt is not None else None


def _peak_factor(t0: datetime) -> float:
    """Return PEAK_MULTIPLIER during IST peak hours, else 1.0."""
    sod = t0.hour * 3600 + t0.minute * 60 + t0.second
    for (start, end) in _PEAK_UTC_WINDOWS:
        if start <= sod <= end:
            return PEAK_MULTIPLIER
    return 1.0


def _event_based_delays(snapshot_json: dict) -> dict[str, float]:
    """
    Compute per-run average delay from TimetableEvent actual vs scheduled times
    using data embedded in snapshot_json runs.
    Returns {run_id: avg_delay_seconds}.
    """
    result: dict[str, float] = {}
    for run in snapshot_json.get("runs", []):
        run_id = run["run_id"]
        delays = []
        for ev in run.get("events", []):
            sched_arr = _parse_ts(ev.get("scheduled_arrival"))
            act_arr = _parse_ts(ev.get("actual_arrival"))
            if sched_arr is not None and act_arr is not None:
                delays.append(max(0.0, act_arr - sched_arr))
            sched_dep = _parse_ts(ev.get("scheduled_departure"))
            act_dep = _parse_ts(ev.get("actual_departure"))
            if sched_dep is not None and act_dep is not None:
                delays.append(max(0.0, act_dep - sched_dep))
        if delays:
            result[run_id] = sum(delays) / len(delays)
    return result


def _detect_short_headway(snapshot_json: dict) -> set[str]:
    """
    Return run_ids for which a preceding train departed from the same
    station within SHORT_HEADWAY_SECONDS.
    """
    # station_code → sorted [(dep_ts, run_id)]
    station_deps: dict[str, list[tuple[float, str]]] = {}
    for run in snapshot_json.get("runs", []):
        run_id = run["run_id"]
        for ev in run.get("events", []):
            dep_ts = _parse_ts(ev.get("scheduled_departure"))
            if dep_ts is not None:
                sc = ev.get("station_code", "")
                station_deps.setdefault(sc, []).append((dep_ts, run_id))

    short_hw: set[str] = set()
    for sc, deps in station_deps.items():
        deps_sorted = sorted(deps, key=lambda x: x[0])
        for i in range(1, len(deps_sorted)):
            gap = deps_sorted[i][0] - deps_sorted[i - 1][0]
            if gap < SHORT_HEADWAY_SECONDS:
                short_hw.add(deps_sorted[i][1])

    return short_hw
