"""
predictors/hetero_graph_builder.py — Rail-Flow AI

HeteroGraphBuilder converts a snapshot_json dict to a PyG HeteroData object
for use by the SAGE-Het GNN predictor (Phase 5).

Node types
----------
  station       : one node per unique station code in the snapshot
  running_train : one node per run_id in the snapshot

Edge types (directed)
---------------------
  (running_train, at_station, station)   : last observed station per train
  (running_train, scheduled_at, station) : every timetable stop
  (running_train, follows, running_train): ordering pairs from alt_pairs
  (station, connects, station)           : corridor edge (DB-backed, optional)

Node feature dimensions
-----------------------
  STATION_FEAT_DIM = 3  : [delay_bucket/4, is_disrupted, degree_norm]
  TRAIN_FEAT_DIM   = 3  : [delay_seconds/3600, progress, is_delayed]

Requires torch + torch_geometric.  Raises ImportError if either is absent.
"""

from __future__ import annotations

from typing import Optional

STATION_FEAT_DIM = 3
TRAIN_FEAT_DIM = 3


class HeteroGraphBuilder:
    """
    Build a ``torch_geometric.data.HeteroData`` object from a snapshot_json dict.

    Usage::

        builder = HeteroGraphBuilder()
        data = builder.build(snapshot_json)
        # data["station"].x           → (N_sta, 3)
        # data["running_train"].x     → (N_tr, 3)
        # data[...].edge_index        → (2, E)
    """

    def build(
        self,
        snapshot_json: dict,
        alt_pairs: Optional[dict] = None,
    ):
        """
        :param snapshot_json: snapshot dict from SnapshotService.
        :param alt_pairs: Optional mapping of {pair_id: AltPair} for ordering edges.
        :returns: ``torch_geometric.data.HeteroData`` object.
        :raises ImportError: if torch or torch_geometric are unavailable.
        """
        import torch
        from torch_geometric.data import HeteroData

        data = HeteroData()

        runs = snapshot_json.get("runs", [])
        live_states = snapshot_json.get("live_states", [])
        disruptions = snapshot_json.get("disruptions", [])

        # ── Station nodes ─────────────────────────────────────────────────────

        station_codes: list[str] = []
        sc_to_idx: dict[str, int] = {}
        for run in runs:
            for ev in run.get("events", []):
                sc = ev.get("station_code", "")
                if sc and sc not in sc_to_idx:
                    sc_to_idx[sc] = len(station_codes)
                    station_codes.append(sc)

        # Stations disrupted in this snapshot
        disrupted: set[str] = {
            d.get("station_code", "") for d in disruptions if d.get("station_code")
        }

        # Count stop events per station (proxy for traffic intensity)
        sc_degree: dict[str, int] = {}
        for run in runs:
            for ev in run.get("events", []):
                sc = ev.get("station_code", "")
                sc_degree[sc] = sc_degree.get(sc, 0) + 1

        station_feats: list[list[float]] = []
        for sc in station_codes:
            bucket = min(sc_degree.get(sc, 0), 4) / 4.0
            is_dis = 1.0 if sc in disrupted else 0.0
            degree_norm = min(sc_degree.get(sc, 0), 20) / 20.0
            station_feats.append([bucket, is_dis, degree_norm])

        data["station"].x = torch.tensor(
            station_feats if station_feats else [[0.0] * STATION_FEAT_DIM],
            dtype=torch.float,
        )

        # ── Running-train nodes ───────────────────────────────────────────────

        rid_to_idx: dict[str, int] = {r["run_id"]: i for i, r in enumerate(runs)}
        live_delays: dict[str, float] = {
            ls["run_id"]: float(ls.get("delay_seconds", 0) or 0)
            for ls in live_states
        }

        train_feats: list[list[float]] = []
        for run in runs:
            rid = run["run_id"]
            delay_s = live_delays.get(rid, 0.0)
            events = run.get("events", [])
            n_actual = sum(1 for e in events if e.get("actual_arrival"))
            progress = n_actual / max(len(events), 1)
            is_delayed = 1.0 if delay_s >= 300.0 else 0.0
            train_feats.append([delay_s / 3600.0, progress, is_delayed])

        data["running_train"].x = torch.tensor(
            train_feats if train_feats else [[0.0] * TRAIN_FEAT_DIM],
            dtype=torch.float,
        )

        # ── Edges: train → last actual station ───────────────────────────────

        at_src: list[int] = []
        at_dst: list[int] = []
        for run in runs:
            rid = run["run_id"]
            t_idx = rid_to_idx[rid]
            events = sorted(run.get("events", []), key=lambda e: e.get("stop_sequence", 0))
            last_sc: Optional[str] = None
            for ev in events:
                if ev.get("actual_arrival"):
                    last_sc = ev.get("station_code", "")
            if last_sc and last_sc in sc_to_idx:
                at_src.append(t_idx)
                at_dst.append(sc_to_idx[last_sc])

        data["running_train", "at_station", "station"].edge_index = (
            torch.tensor([at_src, at_dst], dtype=torch.long)
            if at_src
            else torch.zeros((2, 0), dtype=torch.long)
        )

        # ── Edges: train → all scheduled stops ───────────────────────────────

        sched_src: list[int] = []
        sched_dst: list[int] = []
        for run in runs:
            rid = run["run_id"]
            t_idx = rid_to_idx[rid]
            for ev in run.get("events", []):
                sc = ev.get("station_code", "")
                if sc in sc_to_idx:
                    sched_src.append(t_idx)
                    sched_dst.append(sc_to_idx[sc])

        data["running_train", "scheduled_at", "station"].edge_index = (
            torch.tensor([sched_src, sched_dst], dtype=torch.long)
            if sched_src
            else torch.zeros((2, 0), dtype=torch.long)
        )

        # ── Edges: train follows train (ordering pairs) ───────────────────────

        ff_src: list[int] = []
        ff_dst: list[int] = []
        for pair in (alt_pairs or {}).values():
            if pair.run_i in rid_to_idx and pair.run_j in rid_to_idx:
                ff_src.append(rid_to_idx[pair.run_i])
                ff_dst.append(rid_to_idx[pair.run_j])

        data["running_train", "follows", "running_train"].edge_index = (
            torch.tensor([ff_src, ff_dst], dtype=torch.long)
            if ff_src
            else torch.zeros((2, 0), dtype=torch.long)
        )

        # ── Edges: station connects station (DB-backed) ───────────────────────

        cs_src, cs_dst = _corridor_edges(sc_to_idx)
        data["station", "connects", "station"].edge_index = (
            torch.tensor([cs_src, cs_dst], dtype=torch.long)
            if cs_src
            else torch.zeros((2, 0), dtype=torch.long)
        )

        return data


# ─────────────────────────────────────────────────────────────────────────────
# Module-level helpers
# ─────────────────────────────────────────────────────────────────────────────

def _corridor_edges(sc_to_idx: dict[str, int]) -> tuple[list[int], list[int]]:
    """Load corridor edges from DB; returns empty lists outside Flask context."""
    try:
        from models import CorridorEdge
        from flask import current_app
        _ = current_app._get_current_object()
    except RuntimeError:
        return [], []

    src_list: list[int] = []
    dst_list: list[int] = []
    for edge in CorridorEdge.query.all():
        frm = edge.from_station_id
        to = edge.to_station_id
        if frm in sc_to_idx and to in sc_to_idx:
            src_list.append(sc_to_idx[frm])
            dst_list.append(sc_to_idx[to])
            if edge.is_bidirectional:
                src_list.append(sc_to_idx[to])
                dst_list.append(sc_to_idx[frm])
    return src_list, dst_list
