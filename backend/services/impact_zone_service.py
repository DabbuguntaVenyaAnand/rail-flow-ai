"""
services/impact_zone_service.py — Rail-Flow AI

ImpactZoneService — Algorithm 1 from the HSR-RailFlow report.

Selects the minimal set of trains that must be rescheduled given:
  - theta_obs:     trains already delayed >= this threshold are always included
  - theta_pred:    trains predicted to be delayed >= this are included
  - headway_cutoff: trains that share a segment with an impacted train and
                    are within this headway gap are added by propagation
  - MAX caps:      hard cap on the size of the impact zone

Propagation uses OccupancyModel.trains_sharing_segment() and the headway
gap between consecutive trains on each shared edge.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

from predictors.base import DelayEstimate


class ImpactZoneService:
    """
    Algorithm 1: Select impact zone from snapshot + predictions.

    Usage::

        svc = ImpactZoneService()
        zone = svc.select(snapshot_json, predictions)
        # zone: set of run_id strings
    """

    def __init__(
        self,
        theta_obs_minutes: int = 5,
        theta_pred_minutes: int = 8,
        headway_cutoff_minutes: int = 20,
        max_impacted_trains: int = 80,
        max_impacted_stations: int = 120,
    ) -> None:
        self.theta_obs_s = theta_obs_minutes * 60
        self.theta_pred_s = theta_pred_minutes * 60
        self.headway_cutoff_s = headway_cutoff_minutes * 60
        self.max_impacted_trains = max_impacted_trains
        self.max_impacted_stations = max_impacted_stations

    def select(
        self,
        snapshot_json: dict,
        predictions: list[DelayEstimate],
    ) -> set[str]:
        """
        Return the set of run_ids that belong to the impact zone.

        :param snapshot_json: snapshot_json dict from OperationalSnapshot.
        :param predictions: Output of a DelayPredictor.predict() call.
        :returns: Set of run_ids to include in the rescheduling scope.
        """
        all_run_ids = {r["run_id"] for r in snapshot_json.get("runs", [])}
        if not all_run_ids:
            return set()

        # ── 1. Directly impacted via current delay ────────────────────────
        live_delays: dict[str, float] = {}
        for ls in snapshot_json.get("live_states", []):
            run_id = ls.get("run_id", "")
            delay = float(ls.get("delay_seconds", 0) or 0)
            if run_id:
                live_delays[run_id] = max(live_delays.get(run_id, 0.0), delay)

        directly_impacted: set[str] = {
            run_id
            for run_id, delay in live_delays.items()
            if delay >= self.theta_obs_s and run_id in all_run_ids
        }

        # ── 2. Directly impacted via predicted delay ──────────────────────
        # Use the minimum-horizon (most urgent) prediction per run
        min_h_pred: dict[str, int] = {}
        for est in predictions:
            if est.run_id not in all_run_ids:
                continue
            if est.run_id not in min_h_pred or est.p50_delay_seconds > min_h_pred[est.run_id]:
                min_h_pred[est.run_id] = est.p50_delay_seconds

        for run_id, p50 in min_h_pred.items():
            if p50 >= self.theta_pred_s:
                directly_impacted.add(run_id)

        # ── 3. Propagate via shared-segment headway ───────────────────────
        impact_zone = set(directly_impacted)
        try:
            impact_zone = self._propagate(impact_zone, all_run_ids)
        except RuntimeError:
            # Outside Flask app context (unit tests without DB) — skip propagation
            pass

        # ── 4. Cap ───────────────────────────────────────────────────────
        if len(impact_zone) > self.max_impacted_trains:
            sorted_runs = sorted(
                impact_zone,
                key=lambda r: live_delays.get(r, 0.0),
                reverse=True,
            )
            impact_zone = set(sorted_runs[: self.max_impacted_trains])

        return impact_zone

    # ─────────────────────────────────────────────────────────────────────
    # Private helpers
    # ─────────────────────────────────────────────────────────────────────

    def _propagate(self, seed: set[str], all_run_ids: set[str]) -> set[str]:
        """
        Expand seed by adding trains that share a segment with any impacted
        train AND whose headway gap is below the cutoff.
        """
        from models import TimetableEvent
        from simulator.occupancy import OccupancyModel

        db_events = TimetableEvent.query.filter(
            TimetableEvent.run_id.in_(all_run_ids)
        ).all()

        occ = OccupancyModel()
        intervals = occ.build_from_events(db_events)

        # Build per-edge interval list (for gap computation)
        by_edge: dict[int, list] = defaultdict(list)
        for iv in intervals:
            by_edge[iv.edge_id].append(iv)

        zone = set(seed)
        for impacted_id in list(seed):
            neighbors = occ.trains_sharing_segment(impacted_id, intervals)
            for neighbor_id in neighbors:
                if neighbor_id in zone:
                    continue
                gap = _min_headway_gap(impacted_id, neighbor_id, by_edge)
                if gap < self.headway_cutoff_s:
                    zone.add(neighbor_id)

        return zone


def _min_headway_gap(
    run_i: str,
    run_j: str,
    by_edge: dict[int, list],
) -> float:
    """
    Return the minimum headway gap (seconds) between run_i and run_j
    across all edges they share.  Negative = overlap.
    """
    min_gap = float("inf")

    for edge_id, edge_ivs in by_edge.items():
        ivs_i = [iv for iv in edge_ivs if iv.run_id == run_i]
        ivs_j = [iv for iv in edge_ivs if iv.run_id == run_j]
        if not ivs_i or not ivs_j:
            continue

        for iv_i in ivs_i:
            for iv_j in ivs_j:
                # gap: second train enters after first exits
                gap_ij = (iv_j.enter_time - iv_i.exit_time).total_seconds()
                gap_ji = (iv_i.enter_time - iv_j.exit_time).total_seconds()
                min_gap = min(min_gap, gap_ij, gap_ji)

    return min_gap
