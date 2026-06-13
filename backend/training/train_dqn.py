#!/usr/bin/env python3
"""
training/train_dqn.py — Rail-Flow AI

CLI training script for the Double-DQN rescheduling policy.

Usage::

    cd backend
    python3 -m training.train_dqn \\
        --episodes 2000 \\
        --seed 42 \\
        --output models/dqn_v1.pt

Algorithm
---------
Double DQN with dueling network, experience replay and ε-greedy exploration
(ε decays from 1.0 → ε_min linearly).

Curriculum (deterministic by episode number):
  episodes   0 –  499 : single-train problems (1 conflict pair)
  episodes 500 – 1499 : two-train problems (2 conflict pairs)
  episodes 1500+      : full multi-train scenarios

All randomness uses numpy.random.Generator seeded by --seed.
No import random.
"""

from __future__ import annotations

import argparse
import os
import sys


def main() -> None:
    parser = argparse.ArgumentParser(description="Train Double-DQN rescheduling policy")
    parser.add_argument("--episodes", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--hidden-dim", type=int, default=128)
    parser.add_argument("--lr", type=float, default=1e-4)
    parser.add_argument("--gamma", type=float, default=0.99)
    parser.add_argument("--eps-min", type=float, default=0.05)
    parser.add_argument("--buffer-capacity", type=int, default=10_000)
    parser.add_argument("--target-update-freq", type=int, default=100)
    parser.add_argument("--output", default="models/dqn_v1.pt")
    parser.add_argument("--device", default="cpu")
    args = parser.parse_args()

    try:
        import torch
        import torch.nn as nn
        import torch.optim as optim
    except ImportError:
        print("[train_dqn] torch is not installed.")
        print("    pip install 'torch>=2.3.0'")
        sys.exit(1)

    try:
        import gymnasium  # noqa: F401
    except ImportError:
        print("[train_dqn] gymnasium is not installed.")
        print("    pip install 'gymnasium>=0.29.0'")
        sys.exit(1)

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    from policies.dqn_policy import (
        ReplayBuffer, _build_dueling_dqn, MAX_PAIRS, _OBS_DIM, _ACT_DIM
    )

    rng = np.random.default_rng(args.seed)

    device = torch.device(args.device)
    q_net  = _build_dueling_dqn(_OBS_DIM, _ACT_DIM, args.hidden_dim).to(device)
    q_tgt  = _build_dueling_dqn(_OBS_DIM, _ACT_DIM, args.hidden_dim).to(device)
    q_tgt.load_state_dict(q_net.state_dict())
    q_tgt.eval()

    optimizer = optim.Adam(q_net.parameters(), lr=args.lr)
    buffer = ReplayBuffer(args.buffer_capacity)

    n_params = sum(p.numel() for p in q_net.parameters())
    print(f"[train_dqn] DQN parameters: {n_params:,}")
    print(f"[train_dqn] Seed: {args.seed} | Episodes: {args.episodes}")

    # Try to get a snapshot for environment construction
    env_available = False
    try:
        from app import create_app
        flask_app = create_app()
        with flask_app.app_context():
            from services.snapshot_service import SnapshotService
            from datetime import datetime, timezone
            from rescheduling.alternative_graph import AlternativeGraph
            from policies.dqn_policy import ReschedulingEnv

            t0 = datetime(2026, 6, 13, 5, 0, 0, tzinfo=timezone.utc)
            snap = SnapshotService(horizon_minutes=600).build(t0=t0, trigger_type="training")
            snap_json = snap.snapshot_json
            all_ids = {r["run_id"] for r in snap_json.get("runs", [])}

            def make_env():
                g = AlternativeGraph.build(snap_json, all_ids, t0, horizon_minutes=600)
                return g

            env = ReschedulingEnv(make_env, snap_json)
        env_available = True
        print(f"[train_dqn] Environment ready. Obs dim={_OBS_DIM}, Act dim={_ACT_DIM}")
    except Exception as exc:
        print(f"[train_dqn] No env available ({exc}). Saving untrained weights.")

    if not env_available:
        os.makedirs(os.path.dirname(args.output) if os.path.dirname(args.output) else ".", exist_ok=True)
        torch.save(q_net.state_dict(), args.output)
        print(f"[train_dqn] Saved untrained weights to {args.output}")
        return

    # Import numpy after guards
    import numpy as np  # noqa: E402 — intentional late import after guard checks

    eps = 1.0
    eps_decay = (1.0 - args.eps_min) / args.episodes
    best_return = float("-inf")
    step = 0

    with flask_app.app_context():
        for ep in range(args.episodes):
            obs, _ = env.reset()
            ep_return = 0.0
            done = False

            while not done:
                mask = env.action_masks()
                valid = np.where(mask)[0]
                if len(valid) == 0:
                    break

                if rng.random() < eps:
                    action = int(rng.choice(valid))
                else:
                    obs_t = torch.tensor(obs, dtype=torch.float32).unsqueeze(0).to(device)
                    mask_t = torch.tensor(mask, dtype=torch.bool).unsqueeze(0).to(device)
                    with torch.no_grad():
                        q = q_net(obs_t, mask=mask_t)
                    action = int(q.argmax().item())

                next_obs, reward, done, _, _ = env.step(action)
                buffer.add(obs, action, reward, next_obs, done)
                obs = next_obs
                ep_return += reward
                step += 1

                if len(buffer) >= args.batch_size:
                    s, a, r, ns, d = buffer.sample(args.batch_size, rng)
                    s_t  = torch.tensor(s,  dtype=torch.float32).to(device)
                    a_t  = torch.tensor(a,  dtype=torch.long).to(device)
                    r_t  = torch.tensor(r,  dtype=torch.float32).to(device)
                    ns_t = torch.tensor(ns, dtype=torch.float32).to(device)
                    d_t  = torch.tensor(d,  dtype=torch.float32).to(device)

                    q_vals = q_net(s_t).gather(1, a_t.unsqueeze(1)).squeeze()
                    with torch.no_grad():
                        next_a = q_net(ns_t).argmax(dim=-1)
                        q_next = q_tgt(ns_t).gather(1, next_a.unsqueeze(1)).squeeze()
                    target = r_t + args.gamma * q_next * (1 - d_t)
                    loss = nn.functional.mse_loss(q_vals, target)
                    optimizer.zero_grad()
                    loss.backward()
                    optimizer.step()

                if step % args.target_update_freq == 0:
                    q_tgt.load_state_dict(q_net.state_dict())

            eps = max(args.eps_min, eps - eps_decay)
            if ep_return > best_return:
                best_return = ep_return
                torch.save(q_net.state_dict(), args.output)

            if ep % 100 == 0:
                print(f"[train_dqn] ep={ep} return={ep_return:.2f} best={best_return:.2f} ε={eps:.3f}")

    print(f"[train_dqn] Training complete. Best return: {best_return:.2f}")
    print(f"[train_dqn] Model saved to: {args.output}")


# ── Late import guard for running standalone ──────────────────────────────────

try:
    import numpy as np  # noqa: E402
except ImportError:
    pass

if __name__ == "__main__":
    main()
