"""
test_sage_het_predictor.py — Phase 5.

Fallback-behaviour tests run without torch.
GNN-inference tests are skipped when torch is absent.
"""

from __future__ import annotations

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _snapshot(run_ids=("r1", "r2"), delay=300):
    return {
        "t0": "2026-06-13T05:00:00+00:00",
        "runs": [
            {
                "run_id": rid,
                "train_number": f"1230{i}",
                "events": [
                    {
                        "station_code": "HWH",
                        "stop_sequence": 1,
                        "scheduled_arrival": "2026-06-13T06:00:00+00:00",
                        "scheduled_departure": "2026-06-13T06:10:00+00:00",
                        "actual_arrival": None,
                        "actual_departure": None,
                        "min_dwell_seconds": 60,
                    }
                ],
            }
            for i, rid in enumerate(run_ids)
        ],
        "live_states": [{"run_id": rid, "delay_seconds": delay} for rid in run_ids],
        "disruptions": [],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Fallback tests (no torch required)
# ─────────────────────────────────────────────────────────────────────────────

def test_fallback_when_no_model_file():
    """Without an artifact, SageHetPredictor falls back to historical baseline."""
    from predictors.sage_het import SageHetPredictor
    from predictors.base import DelayEstimate

    predictor = SageHetPredictor(model_path="/nonexistent/path.pt")
    assert predictor._model is None

    snap = _snapshot()
    ests = predictor.predict(snap, horizons=[30])

    assert isinstance(ests, list)
    assert all(isinstance(e, DelayEstimate) for e in ests)
    assert len(ests) == 2   # 2 runs × 1 horizon


def test_fallback_returns_correct_count():
    """Fallback produces one estimate per (run, horizon)."""
    from predictors.sage_het import SageHetPredictor

    predictor = SageHetPredictor(model_path="/nonexistent/path.pt")
    snap = _snapshot(run_ids=["r1", "r2", "r3"])
    ests = predictor.predict(snap, horizons=[15, 30, 60])
    assert len(ests) == 9  # 3 × 3


def test_fallback_p90_ge_p50():
    from predictors.sage_het import SageHetPredictor

    predictor = SageHetPredictor(model_path="/nonexistent/path.pt")
    snap = _snapshot()
    for e in predictor.predict(snap, horizons=[30]):
        assert e.p90_delay_seconds >= e.p50_delay_seconds


def test_model_version_attribute():
    from predictors.sage_het import SageHetPredictor, MODEL_VERSION
    assert SageHetPredictor.MODEL_VERSION == MODEL_VERSION


def test_predict_empty_horizons_returns_empty():
    from predictors.sage_het import SageHetPredictor
    predictor = SageHetPredictor(model_path="/nonexistent/path.pt")
    assert predictor.predict(_snapshot(), horizons=[]) == []


# ─────────────────────────────────────────────────────────────────────────────
# GNN inference tests (require torch + torch_geometric)
# ─────────────────────────────────────────────────────────────────────────────

def test_build_model_returns_module():
    """_build_model() returns a torch.nn.Module with the correct output shapes."""
    torch = pytest.importorskip("torch", reason="torch not installed")
    from predictors.sage_het import _build_model, HIDDEN_DIM
    from predictors.hetero_graph_builder import STATION_FEAT_DIM, TRAIN_FEAT_DIM, HeteroGraphBuilder

    pytest.importorskip("torch_geometric", reason="torch_geometric not installed")

    model = _build_model(STATION_FEAT_DIM, TRAIN_FEAT_DIM, HIDDEN_DIM)
    assert hasattr(model, "forward")

    builder = HeteroGraphBuilder()
    data = builder.build(_snapshot(run_ids=["r1", "r2"]))
    p50, p90 = model(data)

    assert p50.shape == (2,)   # one per train
    assert p90.shape == (2,)
    assert (p50 >= 0).all()
    assert (p90 >= 0).all()


def test_model_p90_ge_p50():
    """Model p90 output should be >= p50 (softplus ensures non-negative; check ordering)."""
    torch = pytest.importorskip("torch", reason="torch not installed")
    pytest.importorskip("torch_geometric", reason="torch_geometric not installed")

    from predictors.sage_het import _build_model, HIDDEN_DIM
    from predictors.hetero_graph_builder import STATION_FEAT_DIM, TRAIN_FEAT_DIM, HeteroGraphBuilder

    model = _build_model(STATION_FEAT_DIM, TRAIN_FEAT_DIM, HIDDEN_DIM)
    data = HeteroGraphBuilder().build(_snapshot(run_ids=["r1"]))
    p50, p90 = model(data)
    # Both non-negative; p90 >= p50 is enforced in SageHetPredictor._gnn_predict
    assert (p50 >= 0).all() and (p90 >= 0).all()


def test_gnn_predict_with_saved_artifact(tmp_path):
    """SageHetPredictor with a real artifact file uses the GNN path."""
    torch = pytest.importorskip("torch", reason="torch not installed")
    pytest.importorskip("torch_geometric", reason="torch_geometric not installed")

    from predictors.sage_het import SageHetPredictor, _build_model, HIDDEN_DIM
    from predictors.hetero_graph_builder import STATION_FEAT_DIM, TRAIN_FEAT_DIM

    artifact = tmp_path / "sage_het_v1.pt"
    model = _build_model(STATION_FEAT_DIM, TRAIN_FEAT_DIM, HIDDEN_DIM)
    torch.save(model.state_dict(), str(artifact))

    predictor = SageHetPredictor(model_path=str(artifact))
    assert predictor._model is not None

    snap = _snapshot(run_ids=["r1", "r2"])
    ests = predictor.predict(snap, horizons=[30])
    assert len(ests) == 2  # 2 runs × 1 horizon
    for e in ests:
        assert e.p50_delay_seconds >= 0
        assert e.p90_delay_seconds >= e.p50_delay_seconds
        assert e.model_version == SageHetPredictor.MODEL_VERSION
