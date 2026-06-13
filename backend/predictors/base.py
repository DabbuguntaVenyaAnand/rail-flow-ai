"""
predictors/base.py — Rail-Flow AI

DelayPredictor protocol and DelayEstimate dataclass.
All predictor implementations must satisfy this interface.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class DelayEstimate:
    """Predicted delay for one run at one look-ahead horizon."""
    run_id: str
    horizon_minutes: int
    p50_delay_seconds: int   # median prediction (rounded to nearest second)
    p90_delay_seconds: int   # 90th-percentile prediction
    model_version: str = "historical_baseline_v1"


@runtime_checkable
class DelayPredictor(Protocol):
    """
    Structural protocol for all delay predictors.

    Implementations: HistoricalBaselinePredictor (Phase 4),
                     SageHetPredictor (Phase 5, optional).
    """

    def predict(
        self,
        snapshot_json: dict,
        horizons: list[int],
    ) -> list[DelayEstimate]:
        """
        Produce delay estimates for every run in snapshot_json at each horizon.

        :param snapshot_json: The ``snapshot_json`` field of an OperationalSnapshot.
        :param horizons: Look-ahead horizons in minutes (e.g. [15, 30, 60]).
        :returns: One :class:`DelayEstimate` per (run_id, horizon) combination.
        """
        ...
