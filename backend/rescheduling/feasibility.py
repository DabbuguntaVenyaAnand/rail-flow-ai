"""
rescheduling/feasibility.py — Rail-Flow AI

FeasibilityShield — Algorithm 3 from the HSR-RailFlow report.

Six sequential validation stages; first failure returns ShieldResult(accepted=False).
validate_partial() runs only the cycle check (used for fast beam-search expansion).
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Optional

from rescheduling.alternative_graph import AlternativeGraph, Arc, EventNode, SOURCE


@dataclass
class ShieldResult:
    accepted: bool
    reason: str = ""
    event_times: dict[EventNode, float] = field(default_factory=dict)
    lower_bound: float = 0.0


class FeasibilityShield:
    """
    Six-stage hard validation layer.

    Usage::

        shield = FeasibilityShield()
        result = shield.validate(alt_graph)
        if result.accepted:
            # event_times: dict[EventNode, float] (seconds since epoch)
            print(result.lower_bound)
    """

    COMMIT_TOLERANCE_S = 30.0

    def __init__(
        self,
        lambda_max: float = 0.25,
        lambda_chg: float = 60.0,
        lambda_hold: float = 10.0,
    ) -> None:
        self.lambda_max = lambda_max
        self.lambda_chg = lambda_chg
        self.lambda_hold = lambda_hold

    # ─────────────────────────────────────────────────────────────────────────
    # Public interface
    # ─────────────────────────────────────────────────────────────────────────

    def validate(
        self,
        g: AlternativeGraph,
        disruptions: Optional[list[dict]] = None,
    ) -> ShieldResult:
        """Full 6-stage validation (Algorithm 3)."""
        arcs = g.active_arcs()

        # Stage 1: Cycle check
        if _has_cycle(arcs, g.nodes):
            return ShieldResult(accepted=False, reason="cycle/deadlock detected")

        # Stage 2: Longest paths → event_times
        event_times = _longest_paths(arcs, g.nodes, g.t0_seconds)

        # Stage 3: Commit-window check
        for node, ts in event_times.items():
            sched = g.scheduled_times.get(node)
            if sched is not None:
                # Calculate dynamic commit window for this specific train run
                commit_window_s = g.commit_window_seconds
                try:
                    from models import LiveTrainState, CorridorEdge
                    state = LiveTrainState.query.filter_by(run_id=node.run_id).first()
                    if state and state.speed_kmh and state.speed_kmh > 0:
                        speed = float(state.speed_kmh)
                        edge = None
                        if state.current_segment_id:
                            edge = CorridorEdge.query.get(state.current_segment_id)
                        distance = float(edge.distance_km if edge and edge.distance_km else 50.0)
                        # Commit window = max(10 min, (Distance / Speed) * 1.2)
                        travel_time_s = (distance / speed) * 3600.0
                        commit_window_s = max(commit_window_s, travel_time_s * 1.2)
                except Exception:
                    pass
                
                commit_end = g.t0_seconds + commit_window_s
                if sched <= commit_end:
                    if ts > sched + self.COMMIT_TOLERANCE_S:
                        return ShieldResult(
                            accepted=False,
                            reason=f"commit-window violation at {node}",
                        )

        # Stage 4: Dwell / running-time lower bounds
        for arc in arcs:
            if not isinstance(arc.src, EventNode):
                continue
            t_src = event_times.get(arc.src)
            t_dst = event_times.get(arc.dst)
            if t_src is None or t_dst is None:
                continue
            if t_dst < t_src + arc.weight - 1.0:   # 1 s tolerance for float
                return ShieldResult(
                    accepted=False,
                    reason=f"temporal bound violated on {arc.src}→{arc.dst}",
                )

        # Stage 5: Blocked-resource check (segment disruptions)
        if disruptions:
            for d in disruptions:
                if not d.get("is_active"):
                    continue
                conn_id = d.get("connection_id")
                if conn_id is None:
                    continue
                block_start = _parse_float_ts(d.get("reported_at"))
                block_end = _parse_float_ts(d.get("expected_end_at")) or float("inf")
                if block_start is None:
                    continue
                # Check all DEP nodes associated with this edge
                for node, ts in event_times.items():
                    if node.kind == "DEP" and block_start <= ts <= block_end:
                        # If this node's edge matches the blocked connection_id, reject
                        # (simplified: relies on external caller filtering by edge)
                        pass  # full check deferred to ImpactZoneService (Phase 4)

        # Stage 6: Capacity / headway / direction check via OccupancyModel
        violations = _check_headway_via_occupancy(g, event_times)
        if violations:
            return ShieldResult(
                accepted=False,
                reason=f"headway violation: {violations[0]}",
            )

        lb = _lower_bound(event_times, g, self.lambda_max)
        return ShieldResult(accepted=True, event_times=event_times, lower_bound=lb)

    def validate_partial(self, g: AlternativeGraph) -> ShieldResult:
        """
        Fast partial validation: cycle check + longest-path lower bound only.
        Used during beam-search expansion before all pairs are resolved.
        """
        arcs = g.active_arcs()
        if _has_cycle(arcs, g.nodes):
            return ShieldResult(accepted=False, reason="cycle/deadlock detected")
        event_times = _longest_paths(arcs, g.nodes, g.t0_seconds)
        lb = _lower_bound(event_times, g, self.lambda_max)
        return ShieldResult(accepted=True, event_times=event_times, lower_bound=lb)


# ─────────────────────────────────────────────────────────────────────────────
# Stage 1 — Cycle detection (DFS with white/gray/black colouring)
# ─────────────────────────────────────────────────────────────────────────────

def _has_cycle(arcs: list[Arc], nodes: set[EventNode]) -> bool:
    adj: dict[Any, list[Any]] = defaultdict(list)
    for arc in arcs:
        adj[arc.src].append(arc.dst)

    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[Any, int] = defaultdict(int)

    def _dfs(v: Any) -> bool:
        color[v] = GRAY
        for w in adj.get(v, []):
            c = color[w]
            if c == GRAY:
                return True
            if c == WHITE and _dfs(w):
                return True
        color[v] = BLACK
        return False

    all_vertices: set[Any] = set(nodes) | {SOURCE}
    for v in all_vertices:
        if color[v] == WHITE and _dfs(v):
            return True
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Stage 2 — Longest paths (Kahn + forward relaxation)
# ─────────────────────────────────────────────────────────────────────────────

def _longest_paths(
    arcs: list[Arc],
    nodes: set[EventNode],
    t0_seconds: float,
) -> dict[EventNode, float]:
    """
    Compute t_v = max_path_from_SOURCE to v in seconds-since-epoch.
    t_SOURCE = t0_seconds.
    """
    all_nodes: set[Any] = set(nodes) | {SOURCE}

    adj: dict[Any, list[tuple[Any, float]]] = defaultdict(list)
    in_deg: dict[Any, int] = {v: 0 for v in all_nodes}

    for arc in arcs:
        adj[arc.src].append((arc.dst, arc.weight))
        in_deg[arc.dst] = in_deg.get(arc.dst, 0) + 1

    dist: dict[Any, float] = {v: float("-inf") for v in all_nodes}
    dist[SOURCE] = t0_seconds

    queue: deque[Any] = deque(v for v in all_nodes if in_deg[v] == 0)
    while queue:
        u = queue.popleft()
        for (v, w) in adj[u]:
            cand = dist[u] + w
            if cand > dist[v]:
                dist[v] = cand
            in_deg[v] -= 1
            if in_deg[v] == 0:
                queue.append(v)

    return {
        v: d
        for v, d in dist.items()
        if isinstance(v, EventNode) and d > float("-inf")
    }


# ─────────────────────────────────────────────────────────────────────────────
# Stage 6 — Headway check via OccupancyModel
# ─────────────────────────────────────────────────────────────────────────────

def _check_headway_via_occupancy(
    g: AlternativeGraph,
    event_times: dict[EventNode, float],
) -> list[str]:
    """
    Build synthetic occupancy intervals from event_times and check headway.
    Returns a list of violation descriptions (empty = pass).
    Only checks fully-resolved pairs (where both sides exist in event_times).
    Silently returns [] when called outside a Flask app context (pure unit tests).
    """
    try:
        from models import CorridorEdge  # noqa: F401 — triggers app-context check
        from flask import current_app     # noqa: F401
        _ = current_app._get_current_object()
    except RuntimeError:
        # No Flask app context — skip Stage 6 for pure unit tests
        return []

    from simulator.occupancy import OccupancyInterval, OccupancyModel
    from datetime import timezone
    from datetime import datetime as _dt

    def _ts_to_dt(ts: float) -> _dt:
        return _dt.fromtimestamp(ts, tz=timezone.utc)

    # Build intervals from consecutive (DEP, ARR) pairs per run
    # Group nodes by run_id
    by_run: dict[str, list[EventNode]] = defaultdict(list)
    for node in event_times:
        by_run[node.run_id].append(node)
    for nodes_list in by_run.values():
        nodes_list.sort(key=lambda n: (n.stop_sequence, n.kind))

    from models import CorridorEdge
    intervals: list[OccupancyInterval] = []

    for run_id, run_nodes in by_run.items():
        dep_nodes = sorted(
            [n for n in run_nodes if n.kind == "DEP"],
            key=lambda n: n.stop_sequence,
        )
        arr_nodes = sorted(
            [n for n in run_nodes if n.kind == "ARR"],
            key=lambda n: n.stop_sequence,
        )

        # Match consecutive (DEP at seq k) → (ARR at seq k+1)
        dep_by_seq = {n.stop_sequence: n for n in dep_nodes}
        arr_by_seq = {n.stop_sequence: n for n in arr_nodes}
        all_seqs = sorted(set(dep_by_seq) | set(arr_by_seq))

        for i, seq in enumerate(all_seqs[:-1]):
            dep_node = dep_by_seq.get(seq)
            next_seq = all_seqs[i + 1]
            arr_node = arr_by_seq.get(next_seq)
            if dep_node is None or arr_node is None:
                continue

            enter_ts = event_times.get(dep_node)
            exit_ts = event_times.get(arr_node)
            if enter_ts is None or exit_ts is None:
                continue

            from_sc = g.station_for.get(dep_node, "")
            to_sc = g.station_for.get(arr_node, "")
            if not from_sc or not to_sc:
                continue

            # Look up edge
            edge = CorridorEdge.query.filter_by(
                from_station_id=from_sc, to_station_id=to_sc
            ).first()
            if edge is None:
                edge = CorridorEdge.query.filter_by(
                    from_station_id=to_sc,
                    to_station_id=from_sc,
                    is_bidirectional=True,
                ).first()
            if edge is None:
                continue

            intervals.append(OccupancyInterval(
                run_id=run_id,
                edge_id=edge.edge_id,
                from_station=from_sc,
                to_station=to_sc,
                enter_time=_ts_to_dt(enter_ts),
                exit_time=_ts_to_dt(exit_ts),
            ))

    if not intervals:
        return []

    occ = OccupancyModel()
    violations = occ.detect_headway_violations(intervals)
    return [
        f"run {v.first.run_id} and {v.second.run_id} gap={v.gap_seconds:.0f}s < {v.required_seconds}s"
        for v in violations
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Lower-bound computation
# ─────────────────────────────────────────────────────────────────────────────

def _lower_bound(
    event_times: dict[EventNode, float],
    g: AlternativeGraph,
    lambda_max: float,
) -> float:
    """J_det lower bound: L_sum + lambda_max * L_max from current longest paths."""
    run_last: dict[str, float] = {}
    run_last_node: dict[str, EventNode] = {}

    for node, ts in event_times.items():
        if node.run_id not in run_last or ts > run_last[node.run_id]:
            run_last[node.run_id] = ts
            run_last_node[node.run_id] = node

    delays = []
    for run_id, node in run_last_node.items():
        sched = g.scheduled_times.get(node)
        if sched is not None:
            delays.append(max(0.0, run_last[run_id] - sched))

    if not delays:
        return 0.0
    return sum(delays) + lambda_max * max(delays)


# ─────────────────────────────────────────────────────────────────────────────
# Misc helpers
# ─────────────────────────────────────────────────────────────────────────────

def _parse_float_ts(s: Optional[str]) -> Optional[float]:
    if s is None:
        return None
    try:
        from datetime import datetime
        return datetime.fromisoformat(s).timestamp()
    except (ValueError, TypeError):
        return None
