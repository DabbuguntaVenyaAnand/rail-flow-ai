"""
test_dqn_policy.py — Phase 6.

ReschedulingEnv tests require gymnasium; skipped if absent.
DQN-inference tests also require torch; those have an additional importorskip.
MaskedDqnPolicy fallback tests run without either dependency.
"""

from __future__ import annotations

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Helpers — build a minimal AlternativeGraph with known conflict pairs
# ─────────────────────────────────────────────────────────────────────────────

def _two_train_graph():
    """
    Build an AlternativeGraph with exactly one alternative pair (2 trains, 1 shared edge).
    Uses the test fixture snapshot from prior phases (via conftest.py fixtures).
    This function runs without DB or Flask app context.
    """
    from rescheduling.alternative_graph import (
        AlternativeGraph, EventNode, Arc, AltPair
    )
    import uuid

    g = AlternativeGraph()
    g.t0_seconds = 1_749_790_800.0   # 2026-06-13 05:00:00 UTC
    g.commit_window_seconds = 600.0

    # Two trains: r_i departs at t0+1h, r_j departs at t0+2h (same shared edge)
    t0 = g.t0_seconds
    nodes = [
        EventNode("ri", 1, "DEP"),
        EventNode("ri", 2, "ARR"),
        EventNode("rj", 1, "DEP"),
        EventNode("rj", 2, "ARR"),
    ]
    for n in nodes:
        g.nodes.add(n)

    sched = {
        EventNode("ri", 1, "DEP"): t0 + 3600,
        EventNode("ri", 2, "ARR"): t0 + 7200,
        EventNode("rj", 1, "DEP"): t0 + 7200,
        EventNode("rj", 2, "ARR"): t0 + 10800,
    }
    g.scheduled_times.update(sched)
    g.station_for = {n: "STA" for n in nodes}

    # Fixed arcs: release from source
    from rescheduling.alternative_graph import SOURCE
    for node, ts in sched.items():
        g.fixed_arcs.append(Arc(SOURCE, node, ts - t0))

    # Alternative pair: ri before rj OR rj before ri
    fwd_src = EventNode("ri", 2, "ARR")
    fwd_dst = EventNode("rj", 1, "DEP")
    bwd_src = EventNode("rj", 2, "ARR")
    bwd_dst = EventNode("ri", 1, "DEP")

    pair_id = str(uuid.uuid4())
    pair = AltPair(
        pair_id=pair_id,
        edge_id=1,
        run_i="ri", dep_stop_i=1, arr_stop_i=2,
        run_j="rj", dep_stop_j=1, arr_stop_j=2,
        fwd=Arc(fwd_src, fwd_dst, 300.0),
        bwd=Arc(bwd_src, bwd_dst, 300.0),
    )
    g.alt_pairs[pair_id] = pair
    g.selections[pair_id] = None
    return g


def _empty_snapshot():
    return {
        "t0": "2026-06-13T05:00:00+00:00",
        "runs": [
            {"run_id": "ri", "train_number": "12301", "events": []},
            {"run_id": "rj", "train_number": "12305", "events": []},
        ],
        "live_states": [],
        "disruptions": [],
    }


# ─────────────────────────────────────────────────────────────────────────────
# ReplayBuffer (no torch / gymnasium required)
# ─────────────────────────────────────────────────────────────────────────────

def test_replay_buffer_add_and_len():
    import numpy as np
    from policies.dqn_policy import ReplayBuffer

    buf = ReplayBuffer(capacity=10)
    for i in range(5):
        buf.add(np.zeros(4), i, float(i), np.ones(4), False)
    assert len(buf) == 5


def test_replay_buffer_wraps_at_capacity():
    import numpy as np
    from policies.dqn_policy import ReplayBuffer

    buf = ReplayBuffer(capacity=3)
    for i in range(5):
        buf.add(np.zeros(4), i, 0.0, np.zeros(4), False)
    assert len(buf) == 3   # capped at capacity


def test_replay_buffer_sample_returns_correct_shapes():
    import numpy as np
    from policies.dqn_policy import ReplayBuffer

    buf = ReplayBuffer(capacity=100)
    obs_dim = 8
    for _ in range(50):
        buf.add(np.zeros(obs_dim), 0, 1.0, np.ones(obs_dim), False)

    rng = np.random.default_rng(42)
    s, a, r, ns, d = buf.sample(16, rng)
    assert s.shape  == (16, obs_dim)
    assert a.shape  == (16,)
    assert r.shape  == (16,)
    assert ns.shape == (16, obs_dim)
    assert d.shape  == (16,)


# ─────────────────────────────────────────────────────────────────────────────
# MaskedDqnPolicy fallback (no torch required)
# ─────────────────────────────────────────────────────────────────────────────

def test_dqn_fallback_without_model():
    """Without a model artifact, MaskedDqnPolicy falls back to BeamSearchPolicy."""
    from policies.dqn_policy import MaskedDqnPolicy

    policy = MaskedDqnPolicy(model_path="/nonexistent/dqn.pt")
    assert policy._model is None

    g = _two_train_graph()
    plans = policy.propose(g)
    assert isinstance(plans, list)
    # BeamSearch produces at least one plan
    assert len(plans) >= 1


def test_dqn_fallback_plans_have_lower_bound():
    from policies.dqn_policy import MaskedDqnPolicy

    policy = MaskedDqnPolicy(model_path="/nonexistent/dqn.pt")
    g = _two_train_graph()
    plans = policy.propose(g)
    for p in plans:
        assert isinstance(p.lower_bound, float)


# ─────────────────────────────────────────────────────────────────────────────
# ReschedulingEnv (requires gymnasium)
# ─────────────────────────────────────────────────────────────────────────────

gymnasium = pytest.importorskip("gymnasium", reason="gymnasium not installed")


def test_env_reset_returns_correct_obs_shape():
    import numpy as np
    from policies.dqn_policy import ReschedulingEnv, MAX_PAIRS

    snap = _empty_snapshot()
    env = ReschedulingEnv(_two_train_graph, snap, max_pairs=MAX_PAIRS)
    obs, info = env.reset()

    assert obs.shape == (env.OBS_DIM,)
    assert obs.dtype == np.float32


def test_env_action_masks_covers_unresolved_pairs():
    from policies.dqn_policy import ReschedulingEnv, MAX_PAIRS

    snap = _empty_snapshot()
    env = ReschedulingEnv(_two_train_graph, snap, max_pairs=MAX_PAIRS)
    env.reset()
    mask = env.action_masks()

    # 1 unresolved pair → exactly 2 valid actions (dir 0 and dir 1)
    assert mask.sum() == 2


def test_env_valid_action_selects_pair():
    from policies.dqn_policy import ReschedulingEnv, MAX_PAIRS

    snap = _empty_snapshot()
    env = ReschedulingEnv(_two_train_graph, snap, max_pairs=MAX_PAIRS)
    env.reset()

    obs, reward, done, _, info = env.step(0)   # pair 0, direction 0

    assert "invalid" not in info
    # After selecting the only pair, graph should be fully resolved → done
    assert done is True


def test_env_invalid_action_returns_negative_reward():
    from policies.dqn_policy import ReschedulingEnv, MAX_PAIRS

    snap = _empty_snapshot()
    env = ReschedulingEnv(_two_train_graph, snap, max_pairs=MAX_PAIRS)
    env.reset()

    # Action for slot beyond the number of pairs → invalid
    invalid_action = (MAX_PAIRS - 1) * 2   # last slot, direction 0
    obs, reward, done, _, info = env.step(invalid_action)

    assert reward == pytest.approx(-1.0)
    assert info.get("invalid") is True


def test_env_done_after_all_pairs_resolved():
    from policies.dqn_policy import ReschedulingEnv, MAX_PAIRS

    snap = _empty_snapshot()
    env = ReschedulingEnv(_two_train_graph, snap, max_pairs=MAX_PAIRS)
    env.reset()

    _, _, done, _, _ = env.step(0)
    assert done is True


# ─────────────────────────────────────────────────────────────────────────────
# DQN inference with a saved artifact (requires torch)
# ─────────────────────────────────────────────────────────────────────────────

def test_dqn_with_saved_artifact_produces_plans(tmp_path):
    """Save an untrained DQN model and verify MaskedDqnPolicy uses it."""
    torch = pytest.importorskip("torch", reason="torch not installed")

    from policies.dqn_policy import (
        _build_dueling_dqn, MaskedDqnPolicy, _OBS_DIM, _ACT_DIM
    )

    artifact = tmp_path / "dqn_v1.pt"
    net = _build_dueling_dqn(_OBS_DIM, _ACT_DIM, 128)
    torch.save(net.state_dict(), str(artifact))

    policy = MaskedDqnPolicy(model_path=str(artifact))
    assert policy._model is not None

    g = _two_train_graph()
    plans = policy.propose(g)
    assert isinstance(plans, list)
    assert len(plans) >= 1
