"""
policies/dqn_policy.py — Rail-Flow AI

MaskedDqnPolicy: Double-DQN policy with action masking for rescheduling.
ReschedulingEnv: Gymnasium environment wrapping one rescheduling episode.
ReplayBuffer: Fixed-capacity experience buffer (numpy, no import random).
DuelingDQN: PyTorch dueling-network Q-function.

Falls back to BeamSearchPolicy when:
  - torch is not installed
  - the DQN artifact does not exist at the configured path
  - POLICY_BACKEND != "dqn"

No import random anywhere in this module.  All randomness uses
numpy.random.Generator seeded explicitly.

Set the artifact path via::

    env DQN_MODEL_PATH=models/dqn_v1.pt

or pass model_path= to MaskedDqnPolicy.
"""

from __future__ import annotations

import os
from collections import deque
from typing import Optional

import numpy as np

_DEFAULT_MODEL_PATH = os.environ.get(
    "DQN_MODEL_PATH",
    os.path.join(os.path.dirname(__file__), "..", "models", "dqn_v1.pt"),
)

# ─────────────────────────────────────────────────────────────────────────────
# Environment
# ─────────────────────────────────────────────────────────────────────────────

MAX_PAIRS = 20                         # fixed observation / action space width
_OBS_DIM = MAX_PAIRS * 3 + 2          # 3 features per pair + 2 global
_ACT_DIM = MAX_PAIRS * 2              # direction 0 or 1 per pair slot


class ReschedulingEnv:
    """
    Gymnasium-compatible environment for rescheduling one snapshot.

    State
    -----
    Flat float32 vector of length ``OBS_DIM``:
      - Per pair slot [dep_i_h, dep_j_h, sel_enc]  (0.0 when unused)
        - dep_*_h   : scheduled departure offset from t0 in hours
        - sel_enc   : 0.0=unresolved, 1.0=fwd, -1.0=bwd
      - Global: [n_unresolved / n_total, t0_hour / 24]

    Action
    ------
    Discrete integer in [0, 2·MAX_PAIRS):
      action = pair_slot * 2 + direction   (direction ∈ {0, 1})
    Invalid actions (resolved pair or out-of-range) return −1 reward and
    do not modify the graph (but do not terminate the episode early).

    Reward
    ------
    -(J_det_after − J_det_before) / 3600.0
    (positive when objective improves)

    Done
    ----
    True when all alternative pairs are resolved.

    Requires gymnasium.  Raises ImportError if not installed.
    """

    OBS_DIM = _OBS_DIM
    ACT_DIM = _ACT_DIM

    metadata: dict = {"render_modes": []}

    def __init__(
        self,
        alt_graph_factory,
        snapshot_json: dict,
        max_pairs: int = MAX_PAIRS,
    ) -> None:
        """
        :param alt_graph_factory: Zero-argument callable returning a fresh
            :class:`~rescheduling.alternative_graph.AlternativeGraph`.
        :param snapshot_json: Snapshot dict (used only for meta-info).
        :param max_pairs: Fixed action/observation space width.
        """
        import gymnasium as gym  # raises ImportError if not installed

        self._factory = alt_graph_factory
        self.snapshot_json = snapshot_json
        self.max_pairs = max_pairs

        obs_dim = max_pairs * 3 + 2
        act_dim = max_pairs * 2
        self.observation_space = gym.spaces.Box(
            low=-10.0, high=100.0, shape=(obs_dim,), dtype=np.float32
        )
        self.action_space = gym.spaces.Discrete(act_dim)

        self._graph = None
        self._pairs: list = []   # ordered list of AltPair (up to max_pairs)
        self._pair_ids: list[str] = []

    def reset(self, seed: Optional[int] = None, options: Optional[dict] = None):
        self._graph = self._factory()
        all_pairs = list(self._graph.alt_pairs.values())
        self._pairs = all_pairs[: self.max_pairs]
        self._pair_ids = [p.pair_id for p in self._pairs]
        return self._obs(), {}

    def step(self, action: int):
        pair_slot = action // 2
        direction = action % 2

        if not self._is_valid(action):
            return self._obs(), -1.0, False, False, {"invalid": True}

        pair_id = self._pair_ids[pair_slot]

        from rescheduling.feasibility import FeasibilityShield
        shield = FeasibilityShield()
        before = shield.validate_partial(self._graph).lower_bound

        self._graph.select_arc(pair_id, direction)

        after = shield.validate_partial(self._graph).lower_bound
        reward = -(after - before) / 3600.0

        done = len(self._graph.unresolved_pairs()) == 0
        return self._obs(), reward, done, False, {}

    def action_masks(self) -> np.ndarray:
        """Boolean mask: True = valid action."""
        mask = np.zeros(self.max_pairs * 2, dtype=bool)
        for i, pid in enumerate(self._pair_ids):
            if self._graph is not None and self._graph.selections.get(pid) is None:
                mask[2 * i] = True
                mask[2 * i + 1] = True
        return mask

    # ─────────────────────────────────────────────────────────────────────────
    # Internal helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _is_valid(self, action: int) -> bool:
        pair_slot = action // 2
        if pair_slot >= len(self._pair_ids):
            return False
        pid = self._pair_ids[pair_slot]
        return self._graph is not None and self._graph.selections.get(pid) is None

    def _obs(self) -> np.ndarray:
        from rescheduling.alternative_graph import EventNode

        obs_dim = self.max_pairs * 3 + 2
        feats = np.zeros(obs_dim, dtype=np.float32)

        if self._graph is None:
            return feats

        t0 = self._graph.t0_seconds
        for i, pair in enumerate(self._pairs):
            dep_i_node = EventNode(pair.run_i, pair.dep_stop_i, "DEP")
            dep_j_node = EventNode(pair.run_j, pair.dep_stop_j, "DEP")
            dep_i = self._graph.scheduled_times.get(dep_i_node, t0)
            dep_j = self._graph.scheduled_times.get(dep_j_node, t0)
            dep_i_h = (dep_i - t0) / 3600.0 if t0 else 0.0
            dep_j_h = (dep_j - t0) / 3600.0 if t0 else 0.0
            sel = self._graph.selections.get(pair.pair_id)
            sel_enc = 0.0 if sel is None else (1.0 if sel == 0 else -1.0)
            base = i * 3
            feats[base]     = dep_i_h
            feats[base + 1] = dep_j_h
            feats[base + 2] = sel_enc

        n_unresolved = len(self._graph.unresolved_pairs())
        n_total = max(len(self._pairs), 1)
        feats[-2] = n_unresolved / n_total
        feats[-1] = (t0 % 86400) / 86400.0 if t0 else 0.0
        return feats


# ─────────────────────────────────────────────────────────────────────────────
# Replay buffer
# ─────────────────────────────────────────────────────────────────────────────

class ReplayBuffer:
    """
    Fixed-capacity circular replay buffer.

    Uses numpy.random.Generator (not import random) for deterministic sampling.
    """

    def __init__(self, capacity: int = 10_000) -> None:
        self._buffer: deque = deque(maxlen=capacity)

    def add(
        self,
        state: np.ndarray,
        action: int,
        reward: float,
        next_state: np.ndarray,
        done: bool,
    ) -> None:
        self._buffer.append((state, action, reward, next_state, done))

    def sample(
        self, batch_size: int, rng: np.random.Generator
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        n = len(self._buffer)
        indices = rng.integers(n, size=batch_size)
        batch = [self._buffer[i] for i in indices]
        states, actions, rewards, next_states, dones = zip(*batch)
        return (
            np.array(states, dtype=np.float32),
            np.array(actions, dtype=np.int64),
            np.array(rewards, dtype=np.float32),
            np.array(next_states, dtype=np.float32),
            np.array(dones, dtype=bool),
        )

    def __len__(self) -> int:
        return len(self._buffer)


# ─────────────────────────────────────────────────────────────────────────────
# Dueling DQN network (PyTorch)
# ─────────────────────────────────────────────────────────────────────────────

def _build_dueling_dqn(obs_dim: int, act_dim: int, hidden_dim: int = 128):
    """Build the dueling-DQN network.  Raises ImportError if torch absent."""
    import torch.nn as nn

    class _DuelingNet(nn.Module):
        def __init__(self):
            super().__init__()
            self.shared = nn.Sequential(
                nn.Linear(obs_dim, hidden_dim),
                nn.ReLU(),
                nn.Linear(hidden_dim, hidden_dim),
                nn.ReLU(),
            )
            self.value_head = nn.Linear(hidden_dim, 1)
            self.adv_head = nn.Linear(hidden_dim, act_dim)

        def forward(self, x, mask=None):
            h = self.shared(x)
            v = self.value_head(h)         # (B, 1)
            a = self.adv_head(h)           # (B, act_dim)
            q = v + (a - a.mean(dim=-1, keepdim=True))
            if mask is not None:
                # Mask invalid actions: set Q to -inf before argmax
                import torch
                q = q.masked_fill(~mask, float("-inf"))
            return q

    return _DuelingNet()


# ─────────────────────────────────────────────────────────────────────────────
# Policy
# ─────────────────────────────────────────────────────────────────────────────

class MaskedDqnPolicy:
    """
    Double-DQN rescheduling policy with masked action selection.

    Falls back to :class:`~policies.beam_search_policy.BeamSearchPolicy` when
    no model artifact is available or torch is not installed.

    Usage::

        policy = MaskedDqnPolicy()            # auto fallback
        plans  = policy.propose(alt_graph)

        policy = MaskedDqnPolicy(model_path="models/dqn_v1.pt")
    """

    MODEL_VERSION = "dqn_v1"

    def __init__(
        self,
        model_path: Optional[str] = None,
        device: str = "cpu",
        shield=None,
        max_pairs: int = MAX_PAIRS,
        hidden_dim: int = 128,
    ) -> None:
        from policies.beam_search_policy import BeamSearchPolicy
        from rescheduling.feasibility import FeasibilityShield

        self._shield = shield or FeasibilityShield()
        self._fallback = BeamSearchPolicy(shield=self._shield)
        self._model = None
        self._device = device
        self._max_pairs = max_pairs
        self._obs_dim = max_pairs * 3 + 2
        self._act_dim = max_pairs * 2

        actual_path = model_path or _DEFAULT_MODEL_PATH
        if os.path.exists(actual_path):
            self._load_model(actual_path, hidden_dim)

    def propose(
        self,
        alt_graph,
        warm_start: Optional[dict] = None,
    ):
        """
        Return a list of :class:`~rescheduling.local_search.CandidatePlan`.

        Uses the DQN when a model is loaded; otherwise delegates to
        BeamSearchPolicy.
        """
        if self._model is None:
            return self._fallback.propose(alt_graph, warm_start=warm_start)
        try:
            return self._dqn_propose(alt_graph, warm_start)
        except Exception:
            return self._fallback.propose(alt_graph, warm_start=warm_start)

    # ─────────────────────────────────────────────────────────────────────────
    # Internal
    # ─────────────────────────────────────────────────────────────────────────

    def _load_model(self, path: str, hidden_dim: int) -> None:
        try:
            import torch

            net = _build_dueling_dqn(self._obs_dim, self._act_dim, hidden_dim)
            state_dict = torch.load(path, map_location=self._device)
            net.load_state_dict(state_dict)
            net.eval()
            self._model = net
        except Exception:
            self._model = None

    def _dqn_propose(self, alt_graph, warm_start):
        """Greedy DQN rollout: always pick the highest-Q valid action."""
        import torch
        from rescheduling.local_search import CandidatePlan

        g = alt_graph.copy()
        if warm_start:
            g.apply_warm_start(warm_start)

        pairs = list(g.alt_pairs.values())[: self._max_pairs]
        pair_ids = [p.pair_id for p in pairs]

        for _ in range(len(pairs)):
            if not g.unresolved_pairs():
                break

            obs = _encode_obs(g, pairs, self._max_pairs)
            obs_t = torch.tensor(obs, dtype=torch.float32).unsqueeze(0)

            mask_np = np.zeros(self._act_dim, dtype=bool)
            for i, pid in enumerate(pair_ids):
                if g.selections.get(pid) is None:
                    mask_np[2 * i] = True
                    mask_np[2 * i + 1] = True
            mask_t = torch.tensor(mask_np, dtype=torch.bool).unsqueeze(0)

            with torch.no_grad():
                q = self._model(obs_t, mask=mask_t)

            action = int(q.argmax(dim=-1).item())
            pair_slot = action // 2
            direction = action % 2

            if pair_slot < len(pair_ids):
                pid = pair_ids[pair_slot]
                if g.selections.get(pid) is None:
                    g.select_arc(pid, direction)

        result = self._shield.validate(g)
        lb = result.lower_bound if result.accepted else float("inf")
        return [CandidatePlan(alt_graph=g, holds={}, lower_bound=lb, policy_name="dqn")]


# ─────────────────────────────────────────────────────────────────────────────
# Module-level helper shared by env + policy
# ─────────────────────────────────────────────────────────────────────────────

def _encode_obs(g, pairs: list, max_pairs: int) -> np.ndarray:
    """Encode alt_graph state as a flat float32 observation vector."""
    from rescheduling.alternative_graph import EventNode

    obs_dim = max_pairs * 3 + 2
    feats = np.zeros(obs_dim, dtype=np.float32)
    t0 = g.t0_seconds

    for i, pair in enumerate(pairs):
        dep_i_node = EventNode(pair.run_i, pair.dep_stop_i, "DEP")
        dep_j_node = EventNode(pair.run_j, pair.dep_stop_j, "DEP")
        dep_i = g.scheduled_times.get(dep_i_node, t0)
        dep_j = g.scheduled_times.get(dep_j_node, t0)
        dep_i_h = (dep_i - t0) / 3600.0 if t0 else 0.0
        dep_j_h = (dep_j - t0) / 3600.0 if t0 else 0.0
        sel = g.selections.get(pair.pair_id)
        sel_enc = 0.0 if sel is None else (1.0 if sel == 0 else -1.0)
        base = i * 3
        feats[base]     = dep_i_h
        feats[base + 1] = dep_j_h
        feats[base + 2] = sel_enc

    n_unresolved = len(g.unresolved_pairs())
    n_total = max(len(pairs), 1)
    feats[-2] = n_unresolved / n_total
    feats[-1] = (t0 % 86400) / 86400.0 if t0 else 0.0
    return feats
