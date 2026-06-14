#!/usr/bin/env python3
"""
training/train_sage_het.py — Rail-Flow AI

CLI training script for the SAGE-Het GNN predictor.

Usage::

    cd backend
    python3 -m training.train_sage_het \\
        --split-date 2026-03-20 \\
        --epochs 50 \\
        --hidden-dim 64 \\
        --lr 1e-3 \\
        --output models/sage_het_v1.pt

Algorithm
---------
1. Load TimetableRun rows that have actual_arrival/departure data.
2. Build per-day snapshot dicts (one per service_date).
3. Split by service_date: before split_date → train, on/after → val.
4. For each snapshot, build a HeteroData via HeteroGraphBuilder and compute
   the target terminal delay per train (actual - scheduled at last stop, hours).
5. Train with pinball loss (q=0.5 for p50, q=0.9 for p90).
6. Save the best-val-loss state_dict.

Falls back to saving untrained weights when no DB is available.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime, timezone


def pinball_loss(pred, target, q: float):
    err = target - pred
    return (err * q).clamp(min=0).mean() + (err * (q - 1)).clamp(min=0).mean()


def _build_snapshot_for_day(run_rows: list, disruptions: list) -> dict:
    """
    Build a minimal snapshot_json dict from a list of TimetableRun ORM objects
    for a single service date.
    """
    runs_data = []
    for run in run_rows:
        events = []
        for ev in sorted(run.events, key=lambda e: e.stop_sequence):
            events.append({
                "event_id":            ev.event_id,
                "station_code":        ev.station_code,
                "stop_sequence":       ev.stop_sequence,
                "scheduled_arrival":   ev.scheduled_arrival.isoformat() if ev.scheduled_arrival else None,
                "scheduled_departure": ev.scheduled_departure.isoformat() if ev.scheduled_departure else None,
                "min_dwell_seconds":   ev.min_dwell_seconds,
                "actual_arrival":      ev.actual_arrival.isoformat() if ev.actual_arrival else None,
                "actual_departure":    ev.actual_departure.isoformat() if ev.actual_departure else None,
            })
        runs_data.append({
            "run_id":       run.run_id,
            "train_number": run.train_number,
            "service_date": run.service_date.isoformat(),
            "run_status":   run.run_status,
            "events":       events,
        })

    now_iso = datetime.now(timezone.utc).isoformat()
    return {
        "t0":          now_iso,
        "horizon_end": now_iso,
        "runs":        runs_data,
        "live_states": [],
        "disruptions": disruptions,
    }


def _terminal_delay_hours(run_dict: dict) -> float:
    """
    Compute the actual delay at the last stop with actual data (in hours).
    Returns 0.0 if no actuals exist.
    """
    events = sorted(run_dict["events"], key=lambda e: e["stop_sequence"], reverse=True)
    for ev in events:
        actual   = ev.get("actual_arrival") or ev.get("actual_departure")
        sched    = ev.get("scheduled_arrival") or ev.get("scheduled_departure")
        if actual and sched:
            try:
                a = datetime.fromisoformat(actual)
                s = datetime.fromisoformat(sched)
                return max(0.0, (a - s).total_seconds() / 3600.0)
            except Exception:
                pass
    return 0.0


def main() -> None:
    parser = argparse.ArgumentParser(description="Train SAGE-Het GNN predictor")
    parser.add_argument("--split-date", default="2026-03-20",
                        help="ISO date for temporal train/val split (train < split, val >= split)")
    parser.add_argument("--epochs", type=int, default=50)
    parser.add_argument("--hidden-dim", type=int, default=64)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--output", default="models/sage_het_v1.pt")
    parser.add_argument("--device", default="cpu")
    args = parser.parse_args()

    try:
        import torch
        import torch.optim as optim
    except ImportError:
        print("[train_sage_het] torch is not installed.")
        print("    pip install 'torch>=2.3.0' 'torch-geometric>=2.5.0'")
        sys.exit(1)

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    from predictors.hetero_graph_builder import STATION_FEAT_DIM, TRAIN_FEAT_DIM, HeteroGraphBuilder
    from predictors.sage_het import _build_model

    device = torch.device(args.device)
    model = _build_model(STATION_FEAT_DIM, TRAIN_FEAT_DIM, args.hidden_dim).to(device)
    optimizer = optim.Adam(model.parameters(), lr=args.lr)
    builder = HeteroGraphBuilder()

    n_params = sum(p.numel() for p in model.parameters())
    print(f"[train_sage_het] Parameters: {n_params:,}")
    print(f"[train_sage_het] Split date : {args.split_date}")
    print(f"[train_sage_het] Epochs     : {args.epochs}")
    print(f"[train_sage_het] Output     : {args.output}")

    # ── Load data from DB ─────────────────────────────────────────────────────
    train_snapshots: list[dict] = []
    val_snapshots:   list[dict] = []

    try:
        from app import create_app
        from models import TimetableRun, TimetableEvent, DisruptionEvent
        import itertools

        flask_app = create_app()
        with flask_app.app_context():
            n_events = TimetableEvent.query.count()
            print(f"[train_sage_het] Found {n_events} TimetableEvent rows.")

            if n_events == 0:
                raise ValueError("No events")

            split_dt = date.fromisoformat(args.split_date)

            # Collect runs that have at least one actual arrival or departure
            runs_with_actuals = (
                TimetableRun.query
                .join(TimetableEvent, TimetableRun.run_id == TimetableEvent.run_id)
                .filter(
                    (TimetableEvent.actual_arrival.isnot(None)) |
                    (TimetableEvent.actual_departure.isnot(None))
                )
                .distinct()
                .all()
            )

            # Build a single shared disruptions list (lightweight)
            disruptions_raw = [
                {
                    "disruption_id":   d.disruption_id,
                    "disruption_type": d.disruption_type,
                    "station_code":    d.station_code,
                    "severity":        d.severity,
                    "is_active":       d.is_active,
                }
                for d in DisruptionEvent.query.filter_by(is_active=False).limit(50).all()
            ]

            print(f"[train_sage_het] Runs with actuals: {len(runs_with_actuals)}")

            # Group by service_date → one snapshot per day
            runs_with_actuals.sort(key=lambda r: r.service_date)
            for svc_date, day_runs in itertools.groupby(runs_with_actuals, key=lambda r: r.service_date):
                day_list = list(day_runs)
                snap = _build_snapshot_for_day(day_list, disruptions_raw)
                if svc_date < split_dt:
                    train_snapshots.append(snap)
                else:
                    val_snapshots.append(snap)

        print(f"[train_sage_het] Train days={len(train_snapshots)}, Val days={len(val_snapshots)}")

    except Exception as exc:
        print(f"[train_sage_het] DB unavailable ({exc}) — saving untrained weights.")
        os.makedirs(os.path.dirname(args.output) if os.path.dirname(args.output) else ".", exist_ok=True)
        torch.save(model.state_dict(), args.output)
        print(f"[train_sage_het] Saved to {args.output}")
        return

    if not train_snapshots:
        print("[train_sage_het] No training snapshots — adjust --split-date. Saving untrained weights.")
        os.makedirs(os.path.dirname(args.output) if os.path.dirname(args.output) else ".", exist_ok=True)
        torch.save(model.state_dict(), args.output)
        return

    # ── Training loop ─────────────────────────────────────────────────────────
    best_val_loss = float("inf")
    os.makedirs(os.path.dirname(args.output) if os.path.dirname(args.output) else ".", exist_ok=True)

    for epoch in range(1, args.epochs + 1):
        model.train()
        epoch_loss = 0.0
        n_train = 0

        for snap in train_snapshots:
            try:
                data = builder.build(snap).to(device)
            except Exception:
                continue

            # Build target: per-train terminal delay in hours
            targets = torch.tensor(
                [_terminal_delay_hours(r) for r in snap["runs"]],
                dtype=torch.float32, device=device,
            )
            if targets.shape[0] == 0:
                continue

            p50, p90 = model(data)
            # Clip output to match target count (HeteroGraphBuilder may filter runs)
            n = min(p50.shape[0], targets.shape[0])
            if n == 0:
                continue
            loss = pinball_loss(p50[:n], targets[:n], 0.5) + \
                   pinball_loss(p90[:n], targets[:n], 0.9)

            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            epoch_loss += loss.item()
            n_train += 1

        # Validation
        model.eval()
        val_loss_total = 0.0
        n_val = 0
        with torch.no_grad():
            for snap in val_snapshots:
                try:
                    data = builder.build(snap).to(device)
                except Exception:
                    continue
                targets = torch.tensor(
                    [_terminal_delay_hours(r) for r in snap["runs"]],
                    dtype=torch.float32, device=device,
                )
                p50, p90 = model(data)
                n = min(p50.shape[0], targets.shape[0])
                if n == 0:
                    continue
                vl = (pinball_loss(p50[:n], targets[:n], 0.5) +
                      pinball_loss(p90[:n], targets[:n], 0.9)).item()
                val_loss_total += vl
                n_val += 1

        val_loss = val_loss_total / max(n_val, 1)
        if val_loss < best_val_loss:
            best_val_loss = val_loss
            torch.save(model.state_dict(), args.output)

        if epoch % 10 == 0:
            avg_train = epoch_loss / max(n_train, 1)
            print(f"[train_sage_het] Epoch {epoch:3d}/{args.epochs}"
                  f" — train={avg_train:.4f}  val={val_loss:.4f}")

    print(f"[train_sage_het] Training complete. Best val loss: {best_val_loss:.4f}")
    print(f"[train_sage_het] Model saved to: {args.output}")


if __name__ == "__main__":
    main()
