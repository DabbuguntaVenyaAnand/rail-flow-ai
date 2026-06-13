"""
predictors/residual_model.py — Rail-Flow AI

ResidualModel stores per-bucket sorted residuals and draws deterministic
samples for scenario generation.

Bucket key: (station_code, train_number, horizon_minutes)
Residual   : actual_arrival − (scheduled_arrival + predicted_p50)

The model is populated at the start of each rolling-horizon cycle from
TimetableEvent rows that have actual timestamps.  Empty buckets return 0.0.

Usage::

    model = ResidualModel()
    model.populate("C019", "12301", 30, residual_seconds=120.0)
    r = model.sample("C019", "12301", 30, scenario_index=0)  # → 120.0
"""

from __future__ import annotations

from collections import defaultdict
from typing import Optional


class ResidualModel:
    """
    Deterministic scenario-perturbation model based on historical residuals.

    Residuals are sorted in ascending order so that:
      - low scenario_index → optimistic (low residual)
      - high scenario_index → pessimistic (high residual)
    """

    def __init__(self) -> None:
        # key: (station_code, train_number, horizon_minutes) → sorted list of residuals
        self._buckets: dict[tuple[str, str, int], list[float]] = defaultdict(list)
        self._sorted_cache: dict[tuple[str, str, int], list[float]] = {}

    # ─────────────────────────────────────────────────────────────────────
    # Populating the model
    # ─────────────────────────────────────────────────────────────────────

    def populate(
        self,
        station_code: str,
        train_number: str,
        horizon_minutes: int,
        residual_seconds: float,
    ) -> None:
        """Add one residual observation to the appropriate bucket."""
        key = (station_code, train_number, horizon_minutes)
        self._buckets[key].append(residual_seconds)
        self._sorted_cache.pop(key, None)   # invalidate sort cache

    # ─────────────────────────────────────────────────────────────────────
    # Sampling
    # ─────────────────────────────────────────────────────────────────────

    def sample(
        self,
        station_code: str,
        train_number: str,
        horizon_minutes: int,
        scenario_index: int,
    ) -> float:
        """
        Return the residual for a given scenario_index.

        The bucket is sorted ascending; index wraps around modulo len.
        Falls back to (station_code, *, horizon_minutes) if no exact match.
        Returns 0.0 if the bucket is empty.
        """
        key = (station_code, train_number, horizon_minutes)
        sorted_r = self._get_sorted(key)
        if sorted_r:
            return sorted_r[scenario_index % len(sorted_r)]

        # Generic fallback: any train at this station + horizon
        sorted_fb = self._fallback(station_code, horizon_minutes)
        if sorted_fb:
            return sorted_fb[scenario_index % len(sorted_fb)]

        return 0.0

    def sample_run_perturbations(
        self,
        run_id: str,
        train_number: str,
        stop_stations: dict[int, str],   # stop_sequence → station_code
        horizon_minutes: int,
        scenario_index: int,
    ) -> dict[tuple[str, int], float]:
        """
        Return perturbation map {(run_id, stop_seq): residual_seconds}
        for one complete run in one scenario.
        """
        result: dict[tuple[str, int], float] = {}
        for seq, station_code in stop_stations.items():
            r = self.sample(station_code, train_number, horizon_minutes, scenario_index)
            result[(run_id, seq)] = r
        return result

    # ─────────────────────────────────────────────────────────────────────
    # Factory
    # ─────────────────────────────────────────────────────────────────────

    @classmethod
    def build_from_snapshot(
        cls,
        snapshot_json: dict,
        predictor_estimates: Optional[list] = None,
        horizon_minutes: int = 30,
    ) -> "ResidualModel":
        """
        Populate from TimetableEvent actuals embedded in snapshot_json.

        Residual = actual_arrival − (scheduled_arrival + p50_predicted).
        When predictor_estimates is None or empty, p50_predicted = 0.
        """
        from models import TimetableEvent

        model = cls()

        # Map run_id → train_number from snapshot runs
        train_numbers: dict[str, str] = {
            r["run_id"]: r.get("train_number", r["run_id"])
            for r in snapshot_json.get("runs", [])
        }

        # p50 predictions by run_id (use max across horizons)
        p50_by_run: dict[str, float] = {}
        for est in (predictor_estimates or []):
            cur = p50_by_run.get(est.run_id, 0.0)
            p50_by_run[est.run_id] = max(cur, est.p50_delay_seconds)

        # Build residuals from per-event actuals in snapshot runs
        for run in snapshot_json.get("runs", []):
            run_id = run["run_id"]
            train_number = train_numbers.get(run_id, run_id)
            p50 = p50_by_run.get(run_id, 0.0)

            for ev in run.get("events", []):
                sched_str = ev.get("scheduled_arrival")
                act_str = ev.get("actual_arrival")
                if sched_str is None or act_str is None:
                    continue
                try:
                    from datetime import datetime
                    sched_ts = datetime.fromisoformat(sched_str).timestamp()
                    act_ts = datetime.fromisoformat(act_str).timestamp()
                    residual = act_ts - sched_ts - p50
                    model.populate(
                        station_code=ev["station_code"],
                        train_number=train_number,
                        horizon_minutes=horizon_minutes,
                        residual_seconds=residual,
                    )
                except (ValueError, KeyError):
                    continue

        return model

    # ─────────────────────────────────────────────────────────────────────
    # Internal helpers
    # ─────────────────────────────────────────────────────────────────────

    def _get_sorted(self, key: tuple) -> list[float]:
        if key not in self._sorted_cache:
            raw = self._buckets.get(key, [])
            self._sorted_cache[key] = sorted(raw) if raw else []
        return self._sorted_cache[key]

    def _fallback(self, station_code: str, horizon_minutes: int) -> list[float]:
        combined: list[float] = []
        for (sc, _tn, hm), vals in self._buckets.items():
            if sc == station_code and hm == horizon_minutes:
                combined.extend(vals)
        return sorted(combined)
