"""
simulator/occupancy.py — Rail-Flow AI

OccupancyModel translates per-stop timetable events into per-segment occupancy
intervals and detects headway violations between consecutive trains.

This is the lowest-level building block used by:
  - Phase 2: ConflictDetector (direct use)
  - Phase 3: FeasibilityShield stage 6 (capacity/headway/direction check)
  - Phase 4: ImpactZoneService (shared-resource propagation)
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from models import TimetableEvent, CorridorEdge, db


@dataclass
class OccupancyInterval:
    """One train occupying one track segment for a time interval."""
    run_id: str
    edge_id: int
    from_station: str
    to_station: str
    enter_time: datetime
    exit_time: datetime


@dataclass
class HeadwayViolation:
    """Two trains too close together on the same segment."""
    first: OccupancyInterval
    second: OccupancyInterval
    gap_seconds: float          # actual gap (negative = overlap)
    required_seconds: int       # min_headway_seconds for this edge


class OccupancyModel:
    """
    Build segment occupancy intervals from a list of TimetableEvents and
    detect headway violations.

    Example::

        model = OccupancyModel()
        intervals = model.build_from_events(events)
        violations = model.detect_headway_violations(intervals)
    """

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def build_from_events(
        self,
        events: list[TimetableEvent],
        use_actual: bool = False,
    ) -> list[OccupancyInterval]:
        """
        Derive segment occupancy from consecutive (run_id, stop_sequence) pairs.

        For each adjacent pair of events in the same run the train occupies
        the corridor edge (departure station → arrival station) from
        *scheduled_departure* at the first stop to *scheduled_arrival* at the
        second stop.  If *use_actual* is True and actual timestamps are
        available, those are used instead.

        Events without a valid departure OR arrival timestamp are skipped.
        """
        # Group events by run_id, sorted by stop_sequence
        by_run: dict[str, list[TimetableEvent]] = defaultdict(list)
        for ev in events:
            by_run[ev.run_id].append(ev)
        for run_events in by_run.values():
            run_events.sort(key=lambda e: e.stop_sequence)

        intervals: list[OccupancyInterval] = []

        for run_id, run_events in by_run.items():
            for i in range(len(run_events) - 1):
                dep_ev = run_events[i]
                arr_ev = run_events[i + 1]

                dep_time = self._departure(dep_ev, use_actual)
                arr_time = self._arrival(arr_ev, use_actual)
                if dep_time is None or arr_time is None:
                    continue

                edge = self._find_edge(
                    dep_ev.station_code, arr_ev.station_code
                )
                if edge is None:
                    continue

                intervals.append(
                    OccupancyInterval(
                        run_id=run_id,
                        edge_id=edge.edge_id,
                        from_station=dep_ev.station_code,
                        to_station=arr_ev.station_code,
                        enter_time=dep_time,
                        exit_time=arr_time,
                    )
                )

        return intervals

    def detect_headway_violations(
        self,
        intervals: list[OccupancyInterval],
        default_min_headway_seconds: int = 300,
    ) -> list[HeadwayViolation]:
        """
        For each segment, sort intervals by enter_time and check that
        consecutive trains observe at least min_headway_seconds gap.

        The gap is measured as: second.enter_time - first.exit_time.
        A negative gap means the trains overlap on the segment.

        :param intervals: Output of :meth:`build_from_events`.
        :param default_min_headway_seconds: Used when no CorridorEdge row exists.
        :returns: List of :class:`HeadwayViolation` objects.
        """
        # Group by edge_id
        by_edge: dict[int, list[OccupancyInterval]] = defaultdict(list)
        for iv in intervals:
            by_edge[iv.edge_id].append(iv)

        # Pre-fetch headway requirements
        headway_map: dict[int, int] = {}
        for edge_id in by_edge:
            edge = db.session.get(CorridorEdge, edge_id)
            headway_map[edge_id] = (
                edge.min_headway_seconds
                if edge and edge.min_headway_seconds
                else default_min_headway_seconds
            )

        violations: list[HeadwayViolation] = []

        for edge_id, edge_intervals in by_edge.items():
            required = headway_map[edge_id]
            sorted_ivs = sorted(edge_intervals, key=lambda iv: iv.enter_time)
            for j in range(len(sorted_ivs) - 1):
                first = sorted_ivs[j]
                second = sorted_ivs[j + 1]
                gap = (
                    second.enter_time - first.exit_time
                ).total_seconds()
                if gap < required:
                    violations.append(
                        HeadwayViolation(
                            first=first,
                            second=second,
                            gap_seconds=gap,
                            required_seconds=required,
                        )
                    )

        return violations

    def trains_sharing_segment(
        self,
        run_id: str,
        intervals: list[OccupancyInterval],
    ) -> list[str]:
        """
        Return run_ids of trains that share at least one segment with *run_id*.
        Used by ImpactZoneService for shared-resource propagation.
        """
        # Find all edge_ids used by the target run
        target_edges = {iv.edge_id for iv in intervals if iv.run_id == run_id}
        if not target_edges:
            return []
        sharing = {
            iv.run_id
            for iv in intervals
            if iv.edge_id in target_edges and iv.run_id != run_id
        }
        return sorted(sharing)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _departure(
        ev: TimetableEvent, use_actual: bool
    ) -> Optional[datetime]:
        if use_actual and ev.actual_departure:
            return ev.actual_departure
        return ev.scheduled_departure

    @staticmethod
    def _arrival(
        ev: TimetableEvent, use_actual: bool
    ) -> Optional[datetime]:
        if use_actual and ev.actual_arrival:
            return ev.actual_arrival
        return ev.scheduled_arrival

    @staticmethod
    def _find_edge(
        from_code: str, to_code: str
    ) -> Optional[CorridorEdge]:
        edge = CorridorEdge.query.filter_by(
            from_station_id=from_code, to_station_id=to_code
        ).first()
        if edge:
            return edge
        # Try bidirectional reverse
        rev = CorridorEdge.query.filter_by(
            from_station_id=to_code,
            to_station_id=from_code,
            is_bidirectional=True,
        ).first()
        return rev
