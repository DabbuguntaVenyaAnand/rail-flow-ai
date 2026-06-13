"""
simulator/event_simulator.py — Rail-Flow AI

EventSimulator materialises absolute event times for a set of runs given
a hold schedule and a precedence assignment.  It implements the longest-path
computation over the alternative graph that is described in Section 6.4 of
the algorithm report and is called by:

  - FeasibilityShield (Phase 3) — stage 2: Longest paths
  - ScenarioEvaluator (Phase 7) — perturbed event-time materialisation
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EventKey:
    """Unique identifier for a single arrival or departure event."""
    run_id: str
    stop_sequence: int
    kind: str   # "ARR" or "DEP"


@dataclass
class ScheduledStop:
    """Input data for one stop in one run."""
    run_id: str
    stop_sequence: int
    station_code: str
    scheduled_arrival: Optional[datetime]
    scheduled_departure: Optional[datetime]
    min_dwell_seconds: int = 0


@dataclass
class MaterialisedEvent:
    """Output: absolute UTC time assigned to one event."""
    key: EventKey
    station_code: str
    time: datetime


@dataclass
class SimulationResult:
    events: dict[EventKey, MaterialisedEvent] = field(default_factory=dict)
    # Terminal delay per run (seconds, relative to scheduled departure at last stop)
    terminal_delays: dict[str, float] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# EventSimulator
# ---------------------------------------------------------------------------

class EventSimulator:
    """
    Compute earliest feasible event times given:
    - a list of :class:`ScheduledStop` rows (the baseline timetable)
    - a dict of additional holds: ``{(run_id, stop_sequence): hold_seconds}``
    - a dict of precedence offsets applied before departure events:
      ``{(run_id_i, stop_i, run_id_j, stop_j): min_gap_seconds}`` meaning
      DEPART(i, stop_i) must precede DEPART(j, stop_j) by at least
      *min_gap_seconds*.

    The algorithm performs a single forward pass in timetable order and then
    applies the precedence constraints in a second pass, iterating until no
    event times change (fixed-point convergence).  Because the alternative
    graph is a DAG after arc selection (guaranteed by FeasibilityShield stage 1),
    convergence is reached in at most N iterations where N = number of events.

    Usage::

        sim = EventSimulator()
        result = sim.materialise(stops, holds={}, precedences={})
    """

    MAX_ITERATIONS = 500   # safety bound; should always converge before this

    def materialise(
        self,
        stops: list[ScheduledStop],
        holds: Optional[dict[tuple[str, int], float]] = None,
        precedences: Optional[dict[tuple[str, int, str, int], float]] = None,
        perturbations: Optional[dict[tuple[str, int], float]] = None,
    ) -> SimulationResult:
        """
        Compute earliest feasible event times.

        :param stops: All timetable stops for the runs being simulated.
        :param holds: Extra hold seconds at specific (run_id, stop_sequence).
        :param precedences: Minimum gap (seconds) from DEPART(i,s_i) to DEPART(j,s_j).
        :param perturbations: Additional delay injected at ARRIVE(run_id, stop_seq)
            in seconds — used by ScenarioEvaluator.
        :returns: :class:`SimulationResult` with materialised events.
        """
        holds = holds or {}
        precedences = precedences or {}
        perturbations = perturbations or {}

        # Index stops by (run_id, stop_sequence)
        stop_index: dict[tuple[str, int], ScheduledStop] = {}
        runs: dict[str, list[ScheduledStop]] = defaultdict(list)
        for s in stops:
            stop_index[(s.run_id, s.stop_sequence)] = s
            runs[s.run_id].append(s)
        for run_stops in runs.values():
            run_stops.sort(key=lambda s: s.stop_sequence)

        # Initialise times from scheduled values
        times: dict[EventKey, float] = {}  # seconds since epoch
        sched_times: dict[EventKey, float] = {}  # immutable scheduled times
        for s in stops:
            arr_key = EventKey(s.run_id, s.stop_sequence, "ARR")
            dep_key = EventKey(s.run_id, s.stop_sequence, "DEP")
            if s.scheduled_arrival:
                ts = s.scheduled_arrival.timestamp()
                times[arr_key] = ts
                sched_times[arr_key] = ts
            if s.scheduled_departure:
                ts = s.scheduled_departure.timestamp()
                times[dep_key] = ts
                sched_times[dep_key] = ts

        # Pre-compute per-(run, stop) departure floors from holds.
        # A hold of H seconds at stop seq means:
        #   dep_time >= scheduled_dep + H   (anchor to scheduled, not current)
        # This prevents the floor from compounding across iterations.
        dep_floors: dict[EventKey, float] = {}
        for s in stops:
            extra = holds.get((s.run_id, s.stop_sequence), 0.0)
            if extra > 0:
                dep_key = EventKey(s.run_id, s.stop_sequence, "DEP")
                base_ts = sched_times.get(dep_key)
                if base_ts is not None:
                    dep_floors[dep_key] = base_ts + extra

        def _enforce_floors() -> bool:
            """Apply hold floors: dep_time >= sched_dep + hold."""
            changed = False
            for dep_key, floor in dep_floors.items():
                current = times.get(dep_key)
                if current is None or floor > current:
                    times[dep_key] = floor
                    changed = True
            return changed

        # Build intra-run running-time constraints
        # DEP(i, seq) + run_time <= ARR(i, seq+1)
        # ARR(i, seq) + dwell >= DEP(i, seq)
        def _forward_pass() -> bool:
            """Returns True if any time was updated."""
            changed = False
            for run_id, run_stops in runs.items():
                for idx, stop in enumerate(run_stops):
                    arr_key = EventKey(run_id, stop.stop_sequence, "ARR")
                    dep_key = EventKey(run_id, stop.stop_sequence, "DEP")

                    # Apply arrival perturbation
                    pert = perturbations.get((run_id, stop.stop_sequence), 0.0)
                    if arr_key in times and pert > 0:
                        new_arr = times[arr_key] + pert
                        if new_arr > times[arr_key]:
                            times[arr_key] = new_arr
                            changed = True

                    # Dwell constraint: DEP >= ARR + min_dwell
                    # (hold floors are handled separately via dep_floors)
                    if arr_key in times:
                        min_dep = times[arr_key] + stop.min_dwell_seconds
                        current_dep = times.get(dep_key)
                        if current_dep is None or min_dep > current_dep:
                            times[dep_key] = min_dep
                            changed = True

                    # Running-time constraint to next stop
                    if idx + 1 < len(run_stops):
                        next_stop = run_stops[idx + 1]
                        next_arr_key = EventKey(
                            run_id, next_stop.stop_sequence, "ARR"
                        )
                        if dep_key in times:
                            # Derive running time from scheduled difference
                            sched_run: float = 0.0
                            if (
                                stop.scheduled_departure
                                and next_stop.scheduled_arrival
                            ):
                                sched_run = (
                                    next_stop.scheduled_arrival.timestamp()
                                    - stop.scheduled_departure.timestamp()
                                )
                                sched_run = max(sched_run, 0.0)
                            min_arr = times[dep_key] + sched_run
                            current_arr = times.get(next_arr_key)
                            if current_arr is None or min_arr > current_arr:
                                times[next_arr_key] = min_arr
                                changed = True

            return changed

        def _precedence_pass() -> bool:
            """Enforce min-gap constraints between departure pairs."""
            changed = False
            for (ri, si, rj, sj), gap in precedences.items():
                dep_i = EventKey(ri, si, "DEP")
                dep_j = EventKey(rj, sj, "DEP")
                if dep_i in times and dep_j in times:
                    min_j = times[dep_i] + gap
                    if min_j > times[dep_j]:
                        times[dep_j] = min_j
                        changed = True
            return changed

        # Iterate until convergence (floors + forward propagation + precedences)
        for _ in range(self.MAX_ITERATIONS):
            ef = _enforce_floors()
            fp = _forward_pass()
            pp = _precedence_pass()
            if not ef and not fp and not pp:
                break

        # Build result
        result = SimulationResult()
        for (run_id, seq, kind), ts in {
            (k.run_id, k.stop_sequence, k.kind): v
            for k, v in times.items()
        }.items():
            key = EventKey(run_id, seq, kind)
            stop = stop_index.get((run_id, seq))
            station = stop.station_code if stop else ""
            result.events[key] = MaterialisedEvent(
                key=key,
                station_code=station,
                time=datetime.fromtimestamp(times[key], tz=timezone.utc),
            )

        # Compute terminal delays
        for run_id, run_stops in runs.items():
            last_stop = run_stops[-1]
            dep_key = EventKey(run_id, last_stop.stop_sequence, "DEP")
            arr_key = EventKey(run_id, last_stop.stop_sequence, "ARR")
            key = dep_key if dep_key in times else arr_key
            if key not in times:
                continue
            sched_ref = (
                last_stop.scheduled_departure
                or last_stop.scheduled_arrival
            )
            if sched_ref is None:
                continue
            delay = times[key] - sched_ref.timestamp()
            result.terminal_delays[run_id] = max(delay, 0.0)

        return result
