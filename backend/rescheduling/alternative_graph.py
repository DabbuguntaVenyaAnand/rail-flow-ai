"""
rescheduling/alternative_graph.py — Rail-Flow AI

AlternativeGraph encodes all train-ordering decisions as selectable arc pairs.
Each pair represents one resource-contention: selecting direction 0 means train i
passes first, direction 1 means train j passes first.  The graph is used by the
FeasibilityShield, GreedyPolicy, and BeamSearchPolicy.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from enum import Enum, auto
from typing import Any, Optional


# ─────────────────────────────────────────────────────────────────────────────
# Sentinel and core data types
# ─────────────────────────────────────────────────────────────────────────────

SOURCE = "__SOURCE__"   # source node; t_SOURCE = t0


class ArcType(Enum):
    SEGMENT = auto()   # running-segment ordering constraint (entry→exit + headway)
    PLATFORM = auto()  # platform dwell conflict arc (arrival→departure interval)


@dataclass(frozen=True, order=True)
class EventNode:
    """One arrival (ARR) or departure (DEP) event for a train at a stop."""
    run_id: str
    stop_sequence: int
    kind: str           # "ARR" or "DEP"

    def __repr__(self) -> str:
        return f"{self.kind}({self.run_id[-8:]},seq={self.stop_sequence})"


@dataclass(frozen=True)
class Arc:
    """Directed constraint: t_dst >= t_src + weight (seconds)."""
    src: Any            # EventNode or SOURCE
    dst: EventNode
    weight: float       # seconds
    arc_type: ArcType = ArcType.SEGMENT


@dataclass
class AltPair:
    """
    A mutually-exclusive ordering pair for two trains on one shared segment.

    fwd ("run_i first"): ARR(run_i, arr_stop_i) → DEP(run_j, dep_stop_j) + h_min
    bwd ("run_j first"): ARR(run_j, arr_stop_j) → DEP(run_i, dep_stop_i) + h_min

    Exactly one arc from the pair is active at any time.
    """
    pair_id: str
    edge_id: int
    run_i: str
    dep_stop_i: int     # stop_seq where run_i departs onto the shared edge
    arr_stop_i: int     # stop_seq where run_i arrives off the shared edge
    run_j: str
    dep_stop_j: int
    arr_stop_j: int
    fwd: Arc
    bwd: Arc
    is_bidirectional_conflict: bool = False


# ─────────────────────────────────────────────────────────────────────────────
# AlternativeGraph
# ─────────────────────────────────────────────────────────────────────────────

class AlternativeGraph:
    """
    Alternative-graph representation of a train rescheduling problem.

    Build via :meth:`build` from a SnapshotService snapshot_json dict.

    Usage::

        g = AlternativeGraph.build(snapshot_json, impact_run_ids, t0)
        for pair in g.unresolved_pairs():
            g2 = g.copy()
            g2.select_arc(pair.pair_id, direction=0)
    """

    DEFAULT_HEADWAY_S = 300.0   # 5 minutes when edge has no setting

    def __init__(self) -> None:
        self.nodes: set[EventNode] = set()
        self.fixed_arcs: list[Arc] = []
        self.alt_pairs: dict[str, AltPair] = {}
        self.selections: dict[str, Optional[int]] = {}  # pair_id → 0|1|None
        self.t0_seconds: float = 0.0
        self.commit_window_seconds: float = 600.0
        # Scheduled times (seconds since epoch) — immutable reference
        self.scheduled_times: dict[EventNode, float] = {}
        # Station code for each event node (for occupancy model integration)
        self.station_for: dict[EventNode, str] = {}

    # ─────────────────────────────────────────────────────────────────────────
    # State queries
    # ─────────────────────────────────────────────────────────────────────────

    def copy(self) -> "AlternativeGraph":
        """Deep-copy enough to safely branch the search."""
        g = AlternativeGraph()
        g.nodes = set(self.nodes)
        g.fixed_arcs = list(self.fixed_arcs)
        g.alt_pairs = dict(self.alt_pairs)        # AltPair is shared (immutable)
        g.selections = dict(self.selections)
        g.t0_seconds = self.t0_seconds
        g.commit_window_seconds = self.commit_window_seconds
        g.scheduled_times = dict(self.scheduled_times)
        g.station_for = dict(self.station_for)
        return g

    def select_arc(self, pair_id: str, direction: int) -> None:
        """Assign a direction (0=fwd, 1=bwd) to an unresolved pair."""
        if pair_id not in self.alt_pairs:
            raise KeyError(f"Unknown pair_id: {pair_id!r}")
        if direction not in (0, 1):
            raise ValueError(f"direction must be 0 or 1, got {direction!r}")
        self.selections[pair_id] = direction

    def active_arcs(self) -> list[Arc]:
        """All fixed arcs plus currently selected alternative arcs."""
        result = list(self.fixed_arcs)
        for pair_id, pair in self.alt_pairs.items():
            sel = self.selections.get(pair_id)
            if sel == 0:
                result.append(pair.fwd)
            elif sel == 1:
                result.append(pair.bwd)
        return result

    def unresolved_pairs(self) -> list[AltPair]:
        """Alternative pairs not yet assigned a direction, in stable order."""
        return [
            p for pid, p in self.alt_pairs.items()
            if self.selections.get(pid) is None
        ]

    def arc_selection(self) -> dict[str, Optional[int]]:
        """Snapshot of current selections (for warm-start hand-off)."""
        return dict(self.selections)

    def apply_warm_start(self, selections: dict[str, Optional[int]]) -> None:
        """
        Seed this graph with a previous run's selections.
        Unknown pair_ids are silently ignored; the shield re-validates afterwards.
        """
        for pair_id, sel in selections.items():
            if pair_id in self.alt_pairs and sel is not None:
                self.selections[pair_id] = sel

    # ─────────────────────────────────────────────────────────────────────────
    # Factory
    # ─────────────────────────────────────────────────────────────────────────

    @classmethod
    def build(
        cls,
        snapshot_json: dict,
        impact_run_ids: set[str],
        t0: datetime,
        commit_window_minutes: int = 10,
        horizon_minutes: int = 60,
    ) -> "AlternativeGraph":
        """
        Build an AlternativeGraph from a snapshot dict.

        :param snapshot_json: The ``snapshot_json`` field of OperationalSnapshot.
        :param impact_run_ids: Run IDs in the impact zone.
        :param t0: Snapshot reference time (UTC-aware datetime).
        :param commit_window_minutes: Width of the frozen commit window.
        :param horizon_minutes: Planning horizon.
        """
        g = cls()
        g.t0_seconds = t0.timestamp()
        g.commit_window_seconds = commit_window_minutes * 60.0

        runs_data = [
            r for r in snapshot_json.get("runs", [])
            if r["run_id"] in impact_run_ids
        ]
        if not runs_data:
            return g

        # edge_id cache: (from_code, to_code) → (edge_id, h_min)
        _edge_cache: dict[tuple[str, str], Optional[tuple[int, float]]] = {}

        def _get_edge_info(frm: str, to: str) -> Optional[tuple[int, float]]:
            key = (frm, to)
            if key in _edge_cache:
                return _edge_cache[key]
            info = _lookup_edge(frm, to)
            _edge_cache[key] = info
            return info

        # ── 1. Build nodes and fixed arcs ──────────────────────────────────

        # Segment map: (run_id, from_station, to_station) → (dep_seq, arr_seq)
        # Used to find stop-sequences for alternative pair creation.
        seg_map: dict[tuple[str, str, str], tuple[int, int]] = {}

        # Segment users: (edge_id) → list of (run_id, dep_seq, arr_seq)
        edge_users: dict[int, list[tuple[str, int, int]]] = defaultdict(list)

        for run in runs_data:
            run_id = run["run_id"]
            events = sorted(run.get("events", []), key=lambda e: e["stop_sequence"])

            for ev in events:
                seq = ev["stop_sequence"]
                sc = ev.get("station_code", "")
                arr_ts = _parse_ts(ev.get("scheduled_arrival"))
                dep_ts = _parse_ts(ev.get("scheduled_departure"))

                if arr_ts is not None:
                    node = EventNode(run_id, seq, "ARR")
                    g.nodes.add(node)
                    g.scheduled_times[node] = arr_ts
                    g.station_for[node] = sc
                    # Release arc: t_node ≥ t0 + (scheduled − t0) = scheduled
                    g.fixed_arcs.append(Arc(SOURCE, node, max(0.0, arr_ts - g.t0_seconds)))

                if dep_ts is not None:
                    node = EventNode(run_id, seq, "DEP")
                    g.nodes.add(node)
                    g.scheduled_times[node] = dep_ts
                    g.station_for[node] = sc
                    g.fixed_arcs.append(Arc(SOURCE, node, max(0.0, dep_ts - g.t0_seconds)))

                # Dwell arc: ARR(i,k) → DEP(i,k)
                if arr_ts is not None and dep_ts is not None:
                    arr_node = EventNode(run_id, seq, "ARR")
                    dep_node = EventNode(run_id, seq, "DEP")
                    min_dwell = float(ev.get("min_dwell_seconds", 0) or 0)
                    g.fixed_arcs.append(Arc(arr_node, dep_node, min_dwell))

            # Running arcs: DEP(i,k) → ARR(i,k+1)
            for idx in range(len(events) - 1):
                ev_k = events[idx]
                ev_k1 = events[idx + 1]
                dep_ts_k = _parse_ts(ev_k.get("scheduled_departure"))
                arr_ts_k1 = _parse_ts(ev_k1.get("scheduled_arrival"))

                if dep_ts_k is None or arr_ts_k1 is None:
                    continue

                dep_node = EventNode(run_id, ev_k["stop_sequence"], "DEP")
                arr_node_next = EventNode(run_id, ev_k1["stop_sequence"], "ARR")
                if dep_node not in g.nodes or arr_node_next not in g.nodes:
                    continue

                frm = ev_k.get("station_code", "")
                to = ev_k1.get("station_code", "")

                # Minimum running time: try edge first, then fall back to scheduled gap
                min_run = arr_ts_k1 - dep_ts_k
                edge_info = _get_edge_info(frm, to)
                if edge_info is not None:
                    _, _ = edge_info  # unpack (we only use h_min in pairs)
                g.fixed_arcs.append(Arc(dep_node, arr_node_next, max(min_run, 0.0)))

                # Record segment usage
                dep_seq = ev_k["stop_sequence"]
                arr_seq = ev_k1["stop_sequence"]
                seg_map[(run_id, frm, to)] = (dep_seq, arr_seq)

                if edge_info is not None:
                    edge_id, _ = edge_info
                    edge_users[edge_id].append((run_id, dep_seq, arr_seq))

        # ── 2. Create alternative pairs for each shared segment ────────────

        processed_pairs: set[tuple[str, str, int]] = set()

        for edge_id, users in edge_users.items():
            if len(users) < 2:
                continue

            # Look up headway for this edge
            h_min = _get_headway(edge_id)

            for i_idx in range(len(users)):
                for j_idx in range(i_idx + 1, len(users)):
                    run_i, dep_i, arr_i = users[i_idx]
                    run_j, dep_j, arr_j = users[j_idx]

                    if run_i == run_j:
                        continue

                    pair_key = (min(run_i, run_j), max(run_i, run_j), edge_id)
                    if pair_key in processed_pairs:
                        continue
                    processed_pairs.add(pair_key)

                    # fwd: run_i before run_j → ARR(run_i, arr_i) → DEP(run_j, dep_j)
                    fwd_src = EventNode(run_i, arr_i, "ARR")
                    fwd_dst = EventNode(run_j, dep_j, "DEP")

                    # bwd: run_j before run_i → ARR(run_j, arr_j) → DEP(run_i, dep_i)
                    bwd_src = EventNode(run_j, arr_j, "ARR")
                    bwd_dst = EventNode(run_i, dep_i, "DEP")

                    # Only create pair if all four nodes are in the graph
                    if not all(
                        n in g.nodes
                        for n in (fwd_src, fwd_dst, bwd_src, bwd_dst)
                    ):
                        continue

                    # Bidirectional single-track: opposing trains need mutual
                    # exclusion (full clearance time), not just minimum headway.
                    dir_i = 1 if arr_i > dep_i else -1
                    dir_j = 1 if arr_j > dep_j else -1
                    is_bidir = (dir_i != dir_j)
                    arc_weight = (
                        h_min + _get_base_run_seconds(edge_id) if is_bidir else h_min
                    )

                    pair_id = str(uuid.uuid4())
                    pair = AltPair(
                        pair_id=pair_id,
                        edge_id=edge_id,
                        run_i=run_i,
                        dep_stop_i=dep_i,
                        arr_stop_i=arr_i,
                        run_j=run_j,
                        dep_stop_j=dep_j,
                        arr_stop_j=arr_j,
                        fwd=Arc(fwd_src, fwd_dst, arc_weight, ArcType.SEGMENT),
                        bwd=Arc(bwd_src, bwd_dst, arc_weight, ArcType.SEGMENT),
                        is_bidirectional_conflict=is_bidir,
                    )
                    g.alt_pairs[pair_id] = pair
                    g.selections[pair_id] = None

        return g


# ─────────────────────────────────────────────────────────────────────────────
# Private helpers (module-level to avoid closure overhead)
# ─────────────────────────────────────────────────────────────────────────────

def _parse_ts(s: Optional[str]) -> Optional[float]:
    """Parse ISO datetime string → Unix timestamp float, or None."""
    if s is None:
        return None
    try:
        return datetime.fromisoformat(s).timestamp()
    except (ValueError, TypeError):
        return None


def _lookup_edge(from_code: str, to_code: str) -> Optional[tuple[int, float]]:
    """Return (edge_id, h_min_seconds) for a corridor edge, or None."""
    from models import CorridorEdge
    edge = CorridorEdge.query.filter_by(
        from_station_id=from_code, to_station_id=to_code
    ).first()
    if edge is None:
        edge = CorridorEdge.query.filter_by(
            from_station_id=to_code,
            to_station_id=from_code,
            is_bidirectional=True,
        ).first()
    if edge is None:
        return None
    h_min = float(edge.min_headway_seconds or AlternativeGraph.DEFAULT_HEADWAY_S)
    return (edge.edge_id, h_min)


def _get_headway(edge_id: int) -> float:
    """Return min_headway_seconds for an edge, defaulting to 300."""
    from models import CorridorEdge, db
    edge = db.session.get(CorridorEdge, edge_id)
    if edge and edge.min_headway_seconds:
        return float(edge.min_headway_seconds)
    return AlternativeGraph.DEFAULT_HEADWAY_S


def _get_base_run_seconds(edge_id: int) -> float:
    """Return base_run_seconds for an edge (full segment traversal time)."""
    from models import CorridorEdge, db
    edge = db.session.get(CorridorEdge, edge_id)
    if edge and edge.base_run_seconds:
        return float(edge.base_run_seconds)
    if edge and edge.base_time_min:
        return float(edge.base_time_min) * 60.0
    return AlternativeGraph.DEFAULT_HEADWAY_S
