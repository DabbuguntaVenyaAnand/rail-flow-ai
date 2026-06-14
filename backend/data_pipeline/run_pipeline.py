"""
data_pipeline/run_pipeline.py — Rail-Flow AI

Master pipeline runner. Executes phases 2–5 in order, then optionally
triggers model training (phases 6–7).

Usage:
    cd backend
    DATABASE_URL="postgresql+psycopg://railflow:railflow@localhost:5432/railflow_db" \\
    DEMO_MODE=false python3 -m data_pipeline.run_pipeline [--phases 2,3,4,5] [--synthetic-only]
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg://railflow:railflow@localhost:5432/railflow_db"
)


def make_app():
    from app import create_app
    return create_app({
        "DEMO_MODE": False,
        "SQLALCHEMY_DATABASE_URI": DB_URL,
    })


def phase2(app):
    print("\n" + "=" * 60)
    print("PHASE 2: Static network import")
    print("=" * 60)
    from data_pipeline.phase2_network import run
    run(app)


def phase3(app, trains):
    print("\n" + "=" * 60)
    print("PHASE 3: Timetable scrape (runningstatus.in)")
    print("=" * 60)
    from data_pipeline.phase3_scrape_timetable import run
    run(app, trains)


def phase4(app, trains, synthetic_only: bool, synthetic_days: int):
    print("\n" + "=" * 60)
    print("PHASE 4: Historical actuals import")
    print("=" * 60)
    from data_pipeline.phase4_actuals import run
    run(app, trains, max_dates=30, synthetic_only=synthetic_only, n_synthetic_days=synthetic_days)


def phase5(app):
    print("\n" + "=" * 60)
    print("PHASE 5: Disruption scenario generation")
    print("=" * 60)
    from data_pipeline.phase5_disruptions import run
    run(app)


def phase6():
    print("\n" + "=" * 60)
    print("PHASE 6: Train SageHet predictor")
    print("=" * 60)
    os.system(
        "python3 -m training.train_sage_het --epochs 100 --output models/sage_het_v1.pt"
    )


def phase7():
    print("\n" + "=" * 60)
    print("PHASE 7: Train DQN policy")
    print("=" * 60)
    os.system(
        f"DATABASE_URL='{DB_URL}' DEMO_MODE=false "
        "python3 -m training.train_dqn --episodes 2000 --seed 42 --output models/dqn_v1.pt"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--phases", default="2,3,4,5",
        help="Comma-separated phases to run (2,3,4,5,6,7). Default: 2,3,4,5"
    )
    parser.add_argument("--train", help="Comma-separated train numbers (default: all)")
    parser.add_argument("--synthetic-only", action="store_true",
                        help="Phase 4: skip web scraping, generate synthetic data only")
    parser.add_argument("--synthetic-days", type=int, default=30,
                        help="Phase 4: days of synthetic data per train")
    args = parser.parse_args()

    phases = {int(p.strip()) for p in args.phases.split(",")}

    from data_pipeline.phase3_scrape_timetable import DEFAULT_TRAINS
    trains = [t.strip() for t in args.train.split(",")] if args.train else DEFAULT_TRAINS

    app = make_app()

    if 2 in phases:
        phase2(app)
    if 3 in phases:
        phase3(app, trains)
    if 4 in phases:
        phase4(app, trains, args.synthetic_only, args.synthetic_days)
    if 5 in phases:
        phase5(app)
    if 6 in phases:
        phase6()
    if 7 in phases:
        phase7()

    print("\n" + "=" * 60)
    print("Pipeline complete.")
    print("=" * 60)
