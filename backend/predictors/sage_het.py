"""
predictors/sage_het.py — Rail-Flow AI

SageHetPredictor: 2-layer heterogeneous GraphSAGE with dual quantile output
heads (p50, p90) targeting the DelayPredictor protocol.

The model uses a manual scatter-based aggregation (no to_hetero wrapper) to
avoid torch_geometric meta-path complexity while preserving the spirit of
HeteroSAGE message passing.

Falls back to HistoricalBaselinePredictor when:
  - torch is not installed
  - the model artifact file does not exist at the configured path
  - an exception is raised during inference

Set the artifact path via:
  env SAGE_HET_MODEL_PATH=models/sage_het_v1.pt

or by passing model_path= to the constructor.
"""

from __future__ import annotations

import os
from typing import Optional

from predictors.base import DelayEstimate
from predictors.hetero_graph_builder import STATION_FEAT_DIM, TRAIN_FEAT_DIM

MODEL_VERSION = "sage_het_v1"
HIDDEN_DIM = 64

_DEFAULT_MODEL_PATH = os.environ.get(
    "SAGE_HET_MODEL_PATH",
    os.path.join(os.path.dirname(__file__), "..", "models", "sage_het_v1.pt"),
)


# ─────────────────────────────────────────────────────────────────────────────
# Model architecture (pure PyTorch — no torch_geometric convolutions)
# ─────────────────────────────────────────────────────────────────────────────

def _build_model(
    station_feat_dim: int = STATION_FEAT_DIM,
    train_feat_dim: int = TRAIN_FEAT_DIM,
    hidden_dim: int = HIDDEN_DIM,
):
    """
    Build the HeteroSAGE model.  Raises ImportError if torch is unavailable.

    Layer 1: project station + train features to hidden_dim.
    Layer 2: scatter-mean from stations to trains via scheduled_at edges,
             concatenate with train embedding, project back to hidden_dim.
    Output : p50 and p90 regression heads (SoftPlus → non-negative seconds).
    """
    import torch
    import torch.nn as nn

    class _SageHetNet(nn.Module):
        def __init__(self):
            super().__init__()
            self.station_proj = nn.Linear(station_feat_dim, hidden_dim)
            self.train_proj = nn.Linear(train_feat_dim, hidden_dim)
            self.conv_proj = nn.Linear(hidden_dim * 2, hidden_dim)
            self.fc = nn.Linear(hidden_dim, hidden_dim)
            self.head_p50 = nn.Linear(hidden_dim, 1)
            self.head_p90 = nn.Linear(hidden_dim, 1)

        def forward(self, data):
            import torch.nn.functional as F

            x_sta = F.relu(self.station_proj(data["station"].x))
            x_tr  = F.relu(self.train_proj(data["running_train"].x))

            edge = data["running_train", "scheduled_at", "station"].edge_index
            n_tr = x_tr.shape[0]
            agg  = torch.zeros(n_tr, hidden_dim, device=x_tr.device)
            cnt  = torch.zeros(n_tr, 1, device=x_tr.device)

            if edge.shape[1] > 0:
                t_idx = edge[0]
                s_idx = edge[1]
                agg.scatter_add_(
                    0,
                    t_idx.unsqueeze(1).expand(-1, hidden_dim),
                    x_sta[s_idx],
                )
                cnt.scatter_add_(
                    0,
                    t_idx.unsqueeze(1),
                    torch.ones(edge.shape[1], 1, device=x_tr.device),
                )

            agg = agg / (cnt + 1e-8)
            h = F.relu(self.conv_proj(torch.cat([x_tr, agg], dim=1)))
            h = F.relu(self.fc(h))

            p50 = F.softplus(self.head_p50(h)).squeeze(-1)
            p90 = F.softplus(self.head_p90(h)).squeeze(-1)
            return p50, p90

    return _SageHetNet()


# ─────────────────────────────────────────────────────────────────────────────
# Predictor
# ─────────────────────────────────────────────────────────────────────────────

class SageHetPredictor:
    """
    GNN-based delay predictor with automatic fallback to the rule-based baseline.

    Usage::

        predictor = SageHetPredictor()
        estimates = predictor.predict(snapshot_json, horizons=[15, 30, 60])

        # With an explicit artifact path:
        predictor = SageHetPredictor(model_path="models/sage_het_v1.pt")
    """

    MODEL_VERSION = MODEL_VERSION

    def __init__(
        self,
        model_path: Optional[str] = None,
        device: str = "cpu",
    ) -> None:
        from predictors.historical_baseline import HistoricalBaselinePredictor

        self._fallback = HistoricalBaselinePredictor()
        self._model = None
        self._device = device
        self._builder = None

        actual_path = model_path or _DEFAULT_MODEL_PATH
        if os.path.exists(actual_path):
            self._load_model(actual_path)

    def predict(
        self,
        snapshot_json: dict,
        horizons: list[int],
    ) -> list[DelayEstimate]:
        """
        Return per-(run, horizon) delay estimates.

        Falls back to HistoricalBaselinePredictor when the GNN is unavailable.
        """
        if not horizons:
            return []
        if self._model is None:
            return self._fallback.predict(snapshot_json, horizons)
        try:
            return self._gnn_predict(snapshot_json, horizons)
        except Exception:
            return self._fallback.predict(snapshot_json, horizons)

    # ─────────────────────────────────────────────────────────────────────────
    # Internal
    # ─────────────────────────────────────────────────────────────────────────

    def _load_model(self, path: str) -> None:
        try:
            import torch
            from predictors.hetero_graph_builder import HeteroGraphBuilder

            model = _build_model(STATION_FEAT_DIM, TRAIN_FEAT_DIM, HIDDEN_DIM)
            state_dict = torch.load(path, map_location=self._device)
            model.load_state_dict(state_dict)
            model.eval()
            self._model = model
            self._builder = HeteroGraphBuilder()
        except Exception:
            self._model = None
            self._builder = None

    def _gnn_predict(
        self,
        snapshot_json: dict,
        horizons: list[int],
    ) -> list[DelayEstimate]:
        import torch

        data = self._builder.build(snapshot_json)
        runs = snapshot_json.get("runs", [])
        n_runs = len(runs)

        with torch.no_grad():
            p50_t, p90_t = self._model(data)

        estimates: list[DelayEstimate] = []
        for i, run in enumerate(runs):
            if i < p50_t.shape[0]:
                p50 = max(0, round(p50_t[i].item() * 3600))
                p90 = max(0, round(p90_t[i].item() * 3600))
                p90 = max(p50, p90)
            else:
                p50 = p90 = 0
            for h in horizons:
                estimates.append(DelayEstimate(
                    run_id=run["run_id"],
                    horizon_minutes=h,
                    p50_delay_seconds=p50,
                    p90_delay_seconds=p90,
                    model_version=MODEL_VERSION,
                ))
        return estimates
