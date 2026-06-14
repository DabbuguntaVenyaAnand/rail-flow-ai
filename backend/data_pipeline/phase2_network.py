"""
data_pipeline/phase2_network.py — Rail-Flow AI

Phase 2: Static network import.
  - Seeds 500 stations (via existing demo seed)
  - Downloads the GitHub route CSVs to build CorridorEdge records
    (base_run_seconds, min_headway_seconds, capacity, direction_group)

Usage:
    cd backend
    DATABASE_URL="postgresql+psycopg://railflow:railflow@localhost:5432/railflow_db" \\
    DEMO_MODE=false python3 -m data_pipeline.phase2_network
"""

from __future__ import annotations

import csv
import io
import os
import sys
import time

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

GITHUB_RAW = "https://raw.githubusercontent.com/ankitaanand28/DA323_IndianRailwayTrainDelayDatasets/main"
TRAIN_LIST_URL = f"{GITHUB_RAW}/Dataset/Train_List.csv"
ROUTE_BASE_URL  = f"{GITHUB_RAW}/Dataset/Train_Route"

# Default operational values where edge-specific data is unavailable
DEFAULT_HEADWAY_S     = 300   # 5 minutes
DEFAULT_BASE_RUN_S    = 3600  # 60 minutes
DEFAULT_CAPACITY      = 1
SESSION = requests.Session()
SESSION.headers["User-Agent"] = "RailFlowAI/2.0 (+research)"


# ─────────────────────────────────────────────────────────────────────────────
# Fetch helpers
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_text(url: str, retries: int = 3) -> str | None:
    for attempt in range(retries):
        try:
            r = SESSION.get(url, timeout=15)
            if r.status_code == 200:
                return r.text
            print(f"  [warn] {url} → {r.status_code}")
            return None
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
            else:
                print(f"  [error] {url}: {e}")
    return None


def _fetch_train_list() -> list[dict]:
    """Return list of {train_number, train_name, from, to, type}."""
    text = _fetch_text(TRAIN_LIST_URL)
    if not text:
        return []
    reader = csv.DictReader(io.StringIO(text))
    rows = []
    for row in reader:
        rows.append({
            "train_number": row.get("Train_Number", "").strip(),
            "train_name":   row.get("Train_Name", "").strip(),
            "from_station": row.get("From_Station", "").strip(),
            "to_station":   row.get("To_Station", "").strip(),
            "train_type":   row.get("Type", "").strip(),
        })
    return rows


def _fetch_route(train_number: str) -> list[dict]:
    """Return list of {station_code, station_name, avg_delay_min} in order."""
    url = f"{ROUTE_BASE_URL}/{train_number}.csv"
    text = _fetch_text(url)
    if not text:
        return []
    reader = csv.DictReader(io.StringIO(text))
    rows = []
    for row in reader:
        code = row.get("Station", "").strip()
        name = row.get("Station_Name", "").strip()
        try:
            avg_delay = float(row.get("Average_Delay(min)", "0").strip() or "0")
        except ValueError:
            avg_delay = 0.0
        if code:
            rows.append({
                "station_code": code,
                "station_name": name,
                "avg_delay_min": avg_delay,
            })
    return rows


# ─────────────────────────────────────────────────────────────────────────────
# Main import
# ─────────────────────────────────────────────────────────────────────────────

def run(app):
    from models import db, Station, CorridorEdge

    with app.app_context():
        # ── 1. Seed 500 stations ─────────────────────────────────────────────
        from fixtures.demo_timetable import load_demo_timetable
        from fixtures.demo_disruptions import load_demo_disruptions
        db.create_all()

        # Seed station data (the 500-station seed runs inside create_app on DEMO_MODE)
        station_count = db.session.query(Station).count()
        print(f"[phase2] Stations in DB: {station_count}")

        # ── 2. Download train list ────────────────────────────────────────────
        print("[phase2] Fetching train list from GitHub …")
        trains = _fetch_train_list()
        print(f"[phase2] {len(trains)} trains found")

        # ── 3. For each train, download route and create corridor edges ───────
        edges_created = 0
        station_codes_seen: set[str] = {s.id for s in db.session.query(Station).all()}

        for t in trains:
            tn = t["train_number"]
            print(f"  → {tn} ({t['train_name']}) …", end=" ", flush=True)
            route = _fetch_route(tn)
            time.sleep(0.3)  # polite rate limit

            if len(route) < 2:
                print("skip (no route)")
                continue

            created = 0
            for idx in range(len(route) - 1):
                frm = route[idx]["station_code"]
                to  = route[idx + 1]["station_code"]

                # Skip if either station not in our 500-station network
                # (we still create it as a placeholder for unknown stations)
                if frm not in station_codes_seen:
                    db.session.merge(Station(
                        id=frm, name=route[idx]["station_name"] or frm,
                        state="Unknown", layer="corridor", priority=3, status="clear",
                    ))
                    station_codes_seen.add(frm)
                if to not in station_codes_seen:
                    db.session.merge(Station(
                        id=to, name=route[idx + 1]["station_name"] or to,
                        state="Unknown", layer="corridor", priority=3, status="clear",
                    ))
                    station_codes_seen.add(to)

                # Idempotent: skip if edge already exists
                existing = CorridorEdge.query.filter_by(
                    from_station_id=frm, to_station_id=to
                ).first()
                if existing:
                    continue

                # Estimate base run time from avg_delay at destination station
                # (very rough heuristic; replaced by actual times in Phase 4)
                avg_d = route[idx + 1]["avg_delay_min"]
                est_run_s = max(DEFAULT_BASE_RUN_S, int(avg_d * 60 * 2))

                edge = CorridorEdge(
                    from_station_id=frm,
                    to_station_id=to,
                    base_time_min=est_run_s / 60.0,
                    is_bidirectional=True,
                    base_run_seconds=est_run_s,
                    min_headway_seconds=DEFAULT_HEADWAY_S,
                    capacity=DEFAULT_CAPACITY,
                    direction_group=t["from_station"],  # group by origin
                    is_enabled=True,
                )
                db.session.add(edge)
                created += 1

            try:
                db.session.commit()
                edges_created += created
                print(f"{len(route)} stops, {created} new edges")
            except Exception as e:
                db.session.rollback()
                print(f"ERROR: {e}")

        print(f"\n[phase2] Done. Total new corridor edges: {edges_created}")

        # ── 4. Load demo timetable + disruptions ──────────────────────────────
        print("[phase2] Loading demo timetable …")
        load_demo_timetable()
        load_demo_disruptions()
        print("[phase2] Demo fixtures loaded.")


if __name__ == "__main__":
    from app import create_app
    _app = create_app({
        "DEMO_MODE": False,
        "SQLALCHEMY_DATABASE_URI": os.environ.get(
            "DATABASE_URL",
            "postgresql+psycopg://railflow:railflow@localhost:5432/railflow_db"
        ),
    })
    run(_app)
    print("[phase2] Complete.")
