"""
data_pipeline/phase4_actuals.py — Rail-Flow AI

Phase 4: Historical actuals import.
Two-pronged approach:
  A) Scrape per-date actual times from runningstatus.in/history/{train_number}
     then /status/{train_number}-on-{YYYYMMDD}
  B) Supplement with synthetic delays from GitHub aggregate delay stats

Usage:
    cd backend
    DATABASE_URL="postgresql+psycopg://railflow:railflow@localhost:5432/railflow_db" \\
    DEMO_MODE=false python3 -m data_pipeline.phase4_actuals \\
        [--train 12301,12302] [--days 30] [--synthetic-only] [--synthetic-days 30]
"""

from __future__ import annotations

import argparse
import csv
import io
import os
import re
import sys
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from itertools import groupby

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE_URL = "https://runningstatus.in"
GITHUB_RAW = "https://raw.githubusercontent.com/ankitaanand28/DA323_IndianRailwayTrainDelayDatasets/main"

SESSION = requests.Session()
SESSION.headers["User-Agent"] = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

from data_pipeline.phase3_scrape_timetable import DEFAULT_TRAINS, TRAIN_NAMES


def _get(url: str, retries: int = 3) -> str | None:
    for attempt in range(retries):
        try:
            r = SESSION.get(url, timeout=20)
            if r.status_code == 200:
                return r.text
            if r.status_code in (429, 503):
                time.sleep(5 * (attempt + 1))
            else:
                return None
        except Exception as e:
            if attempt == retries - 1:
                print(f"  [err] {url}: {e}")
    return None


def _parse_time(raw: str, base_date: date) -> datetime | None:
    raw = raw.strip()
    if not raw or raw in ("-", "--", "N/A"):
        return None
    for fmt in ("%I:%M %p", "%H:%M", "%I:%M%p"):
        try:
            t = datetime.strptime(raw.upper(), fmt).time()
            return datetime.combine(base_date, t, tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _scrape_history_dates(train_number: str, max_dates: int = 30) -> list[str]:
    url = f"{BASE_URL}/history/{train_number}"
    html = _get(url)
    if not html:
        return []

    soup = BeautifulSoup(html, "lxml")
    pattern = re.compile(rf"/status/{train_number}-on-(\d{{8}})")
    dates, seen = [], set()
    for a in soup.find_all("a", href=True):
        m = pattern.search(a["href"])
        if m and m.group(1) not in seen:
            seen.add(m.group(1))
            dates.append(m.group(1))
            if len(dates) >= max_dates:
                break
    return dates


def _extract_times_from_cell(raw: str, base_date: date) -> tuple[datetime | None, datetime | None]:
    """Two time patterns from a combined arr/dep cell like '07:03 PM|07:05 PM'."""
    pattern = re.compile(r"\d{1,2}:\d{2}\s*(?:AM|PM)", re.IGNORECASE)
    matches = pattern.findall(raw)
    arr = _parse_time(matches[0], base_date) if len(matches) >= 1 else None
    dep = _parse_time(matches[1], base_date) if len(matches) >= 2 else None
    if arr and dep is None:
        dep = arr
        arr = None
    return arr, dep


def _scrape_actuals_for_date(train_number: str, date_str: str) -> list[dict] | None:
    """
    Same column layout as scrape_schedule:
      col 0: empty, col 1: station+code, col 2: sch arr/dep, col 3: actual arr/dep
    """
    url = f"{BASE_URL}/status/{train_number}-on-{date_str}"
    html = _get(url)
    if not html:
        return None

    soup = BeautifulSoup(html, "lxml")
    base = datetime.strptime(date_str, "%Y%m%d").date()

    table = None
    for t in soup.find_all("table"):
        hdrs = [th.get_text(strip=True).lower() for th in t.find_all("th")]
        if any("station" in h for h in hdrs):
            table = t
            break

    rows_raw = table.find_all("tr") if table else soup.select("tr")

    stops = []
    for row in rows_raw:
        cells = [td.get_text(separator="|", strip=True) for td in row.find_all(["td", "th"])]
        if len(cells) < 4:
            continue

        station_raw = cells[1] if len(cells) > 1 else ""
        code_match = re.search(r"\(([A-Z]{2,8})\)", station_raw)
        if not code_match:
            continue
        code = code_match.group(1)

        # Column 3 = actual arr/dep
        actual_raw = cells[3] if len(cells) > 3 else ""
        actual_arr, actual_dep = _extract_times_from_cell(actual_raw, base)

        if actual_arr is None and actual_dep is None:
            continue

        stops.append({
            "station_code":     code,
            "actual_arrival":   actual_arr,
            "actual_departure": actual_dep,
        })

    return stops if stops else None


def _load_avg_delays(train_number: str) -> dict[str, float]:
    url = f"{GITHUB_RAW}/Dataset/Train_Route/{train_number}.csv"
    try:
        r = SESSION.get(url, timeout=15)
        if r.status_code != 200:
            return {}
        out = {}
        for row in csv.DictReader(io.StringIO(r.text)):
            code = row.get("Station", "").strip()
            try:
                avg_d = float(row.get("Average_Delay(min)", "0").strip() or "0")
            except ValueError:
                avg_d = 0.0
            if code:
                out[code] = avg_d
        return out
    except Exception:
        return {}


def _generate_synthetic_actuals(
    sched_stops: list[dict],
    avg_delays: dict[str, float],
    rng,
    n_days: int,
    start_date: date,
) -> list[dict]:
    import numpy as np

    records = []
    for day_offset in range(n_days):
        run_date = start_date + timedelta(days=day_offset)
        cumulative_delay_s = 0.0

        for stop in sched_stops:
            sc = stop["station_code"]
            avg_d = max(avg_delays.get(sc, 5.0), 0.5)
            sigma = 0.8
            mu = float(np.log(avg_d))
            sampled_min = float(rng.lognormal(mu, sigma))
            delay_s = max(0.0, sampled_min * 60.0) + cumulative_delay_s
            cumulative_delay_s = delay_s * 0.7

            sched_arr = stop.get("scheduled_arrival")
            sched_dep = stop.get("scheduled_departure")
            actual_arr = (sched_arr + timedelta(seconds=delay_s)) if sched_arr else None
            actual_dep = (sched_dep + timedelta(seconds=delay_s)) if sched_dep else None

            records.append({
                "run_date":         run_date,
                "station_code":     sc,
                "actual_arrival":   actual_arr,
                "actual_departure": actual_dep,
            })

    return records


def _upsert_actuals_for_date(app, train_number: str, run_date: date, actuals: list[dict]) -> int:
    from models import db, Train, TimetableRun, TimetableEvent, Station

    with app.app_context():
        # Ensure Train exists
        if not db.session.get(Train, train_number):
            db.session.add(Train(
                train_number=train_number,
                train_name=TRAIN_NAMES.get(train_number, f"Train {train_number}"),
            ))
            db.session.flush()

        run = TimetableRun.query.filter_by(
            train_number=train_number, service_date=run_date
        ).first()

        if not run:
            # Create a historical run using the canonical run's events as template
            canonical = TimetableRun.query.filter_by(train_number=train_number).first()
            if not canonical:
                return 0  # no scheduled timetable to reference

            run_id = str(uuid.uuid4())
            run = TimetableRun(
                run_id=run_id,
                train_number=train_number,
                service_date=run_date,
                run_status="historical",
            )
            db.session.add(run)
            db.session.flush()

            # Copy scheduled stop structure from canonical run, with actual_date offset
            canonical_events = (
                TimetableEvent.query
                .filter_by(run_id=canonical.run_id)
                .order_by(TimetableEvent.stop_sequence)
                .all()
            )
            delta = timedelta(days=(run_date - canonical.service_date).days)
            for ce in canonical_events:
                evt = TimetableEvent(
                    run_id=run_id,
                    station_code=ce.station_code,
                    stop_sequence=ce.stop_sequence,
                    scheduled_arrival=(ce.scheduled_arrival + delta) if ce.scheduled_arrival else None,
                    scheduled_departure=(ce.scheduled_departure + delta) if ce.scheduled_departure else None,
                    min_dwell_seconds=ce.min_dwell_seconds,
                    actual_arrival=None,
                    actual_departure=None,
                )
                db.session.add(evt)
            db.session.flush()

        # Map actuals by station_code
        events = {e.station_code: e for e in TimetableEvent.query.filter_by(run_id=run.run_id).all()}
        updated = 0
        for act in actuals:
            sc = act["station_code"]
            if sc in events:
                e = events[sc]
                if act.get("actual_arrival"):
                    e.actual_arrival = act["actual_arrival"]
                if act.get("actual_departure"):
                    e.actual_departure = act["actual_departure"]
                updated += 1

        try:
            db.session.commit()
            return updated
        except Exception as ex:
            db.session.rollback()
            print(f"  [db err] {train_number}/{run_date}: {ex}")
            return 0


def run(app, train_numbers: list[str], max_dates: int = 30, synthetic_only: bool = False, n_synthetic_days: int = 30):
    import numpy as np

    rng = np.random.default_rng(12345)
    total_scraped = 0
    total_synthetic = 0

    for tn in train_numbers:
        print(f"\n[phase4] {tn}", flush=True)

        avg_delays = _load_avg_delays(tn)
        time.sleep(0.3)

        if not synthetic_only:
            print(f"  → scraping history … ", end="", flush=True)
            dates = _scrape_history_dates(tn, max_dates=max_dates)
            time.sleep(0.8)
            print(f"{len(dates)} dates")
            for date_str in dates:
                actuals = _scrape_actuals_for_date(tn, date_str)
                time.sleep(1.2)
                if actuals:
                    run_date = datetime.strptime(date_str, "%Y%m%d").date()
                    n = _upsert_actuals_for_date(app, tn, run_date, actuals)
                    print(f"    {date_str}: {n} stops")
                    total_scraped += n

        # Synthetic generation
        with app.app_context():
            from models import TimetableRun, TimetableEvent
            canonical = TimetableRun.query.filter_by(train_number=tn, run_status="scheduled").first()

        if not canonical:
            print(f"  → no scheduled run found, skipping synthetic")
            continue

        with app.app_context():
            from models import TimetableEvent
            sched_stops = [
                {
                    "station_code":        e.station_code,
                    "scheduled_arrival":   e.scheduled_arrival,
                    "scheduled_departure": e.scheduled_departure,
                }
                for e in TimetableEvent.query
                    .filter_by(run_id=canonical.run_id)
                    .order_by(TimetableEvent.stop_sequence)
                    .all()
            ]

        if not sched_stops:
            continue

        synthetic = _generate_synthetic_actuals(
            sched_stops, avg_delays, rng,
            n_days=n_synthetic_days,
            start_date=date(2026, 3, 1),
        )

        synthetic.sort(key=lambda x: x["run_date"])
        day_count = 0
        for run_date, day_records in groupby(synthetic, key=lambda x: x["run_date"]):
            day_list = list(day_records)
            n = _upsert_actuals_for_date(app, tn, run_date, day_list)
            total_synthetic += n
            day_count += 1

        print(f"  → synthetic: {day_count} days, {total_synthetic} stops total so far")

    print(f"\n[phase4] Done. Scraped={total_scraped}, Synthetic={total_synthetic} stops.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--train", help="Comma-separated train numbers")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--synthetic-only", action="store_true")
    parser.add_argument("--synthetic-days", type=int, default=30)
    args = parser.parse_args()

    trains = [t.strip() for t in args.train.split(",")] if args.train else DEFAULT_TRAINS

    from app import create_app
    _app = create_app({
        "DEMO_MODE": False,
        "SQLALCHEMY_DATABASE_URI": os.environ.get(
            "DATABASE_URL",
            "postgresql+psycopg://railflow:railflow@localhost:5432/railflow_db"
        ),
    })
    run(_app, trains, max_dates=args.days, synthetic_only=args.synthetic_only, n_synthetic_days=args.synthetic_days)
