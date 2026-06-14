"""
data_pipeline/phase3_scrape_timetable.py — Rail-Flow AI

Phase 3: Timetable import.
Scrapes static scheduled stop data from runningstatus.in for each train
and loads it into trains + timetable_runs + timetable_events tables.

Source: https://runningstatus.in/status/{train_number}
        → station codes, scheduled arrival/departure, stop sequence

Usage:
    cd backend
    DATABASE_URL="postgresql+psycopg://railflow:railflow@localhost:5432/railflow_db" \\
    DEMO_MODE=false python3 -m data_pipeline.phase3_scrape_timetable [--train 12301,12302]
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
import uuid
from datetime import date, datetime, timedelta, timezone

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE_URL = "https://runningstatus.in"
SESSION  = requests.Session()
SESSION.headers["User-Agent"] = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

SERVICE_DATE = date(2026, 6, 13)   # canonical service date for scheduled entries

DEFAULT_TRAINS = [
    "12301", "12302",
    "12303", "12304",
    "12305", "12306",
    "13181", "13182",
    "12423", "12424",
    "12507", "12508",
    "12509", "12510",
    "15629", "15630",
    "12503", "12504",
    "15909", "15910",
    "12519", "12520",
    "12346",
    "14037", "14038",
    "12515", "12516",
    "20501", "20503", "20504",
    "22449", "22450",
    "22501", "22502",
]

TRAIN_NAMES = {
    "12301": "Howrah Rajdhani (UP)",
    "12302": "Howrah Rajdhani (DN)",
    "12303": "Poorva Express (UP)",
    "12304": "Poorva Express (DN)",
    "12305": "Rajdhani Express (NDLS-HWH UP)",
    "12306": "Rajdhani Express (HWH-NDLS DN)",
    "13181": "Kaziranga Express (UP)",
    "13182": "Kaziranga Express (DN)",
    "12423": "Dibrugarh Rajdhani (UP)",
    "12424": "Dibrugarh Rajdhani (DN)",
    "12507": "Guwahati Express (UP)",
    "12508": "Guwahati Express (DN)",
    "12509": "Guwahati-Bangalore Express (UP)",
    "12510": "Guwahati-Bangalore Express (DN)",
    "15629": "Guwahati-Mangalore Express (UP)",
    "15630": "Guwahati-Mangalore Express (DN)",
    "12503": "Agartala Express (UP)",
    "12504": "Agartala Express (DN)",
    "15909": "Avadh Assam Express (UP)",
    "15910": "Avadh Assam Express (DN)",
    "12519": "Bhubaneswar-Kamakhya Express (UP)",
    "12520": "Bhubaneswar-Kamakhya Express (DN)",
    "12346": "Saraighat Express",
    "14037": "Ganga Satluj Express (UP)",
    "14038": "Ganga Satluj Express (DN)",
    "12515": "Guwahati-Trivandrum Express (UP)",
    "12516": "Guwahati-Trivandrum Express (DN)",
    "20501": "Vande Bharat NE (1)",
    "20503": "Vande Bharat NE (2)",
    "20504": "Vande Bharat NE (3)",
    "22449": "Bihar Sampark Kranti (UP)",
    "22450": "Bihar Sampark Kranti (DN)",
    "22501": "New Tinsukia-Delhi Express (UP)",
    "22502": "New Tinsukia-Delhi Express (DN)",
}


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


def _extract_times_from_cell(raw: str, base_date: date) -> tuple[datetime | None, datetime | None]:
    """
    runningstatus.in puts Arr and Dep in a single cell like "06:47 PM06:49 PM"
    or "--04:50 PM" (source station).  Extract up to two time patterns.
    """
    pattern = re.compile(r"\d{1,2}:\d{2}\s*(?:AM|PM)", re.IGNORECASE)
    matches = pattern.findall(raw)
    arr = _parse_time(matches[0], base_date) if len(matches) >= 1 else None
    dep = _parse_time(matches[1], base_date) if len(matches) >= 2 else None
    # Source/terminal stations only have one time (which is dep or arr)
    if arr and dep is None:
        dep = arr
        arr = None
    return arr, dep


def scrape_schedule(train_number: str) -> list[dict] | None:
    """
    Page structure at https://runningstatus.in/status/{N}:
      col 0: empty icon column
      col 1: "STATION NAME (CODE)\nAvg Speed: --"
      col 2: "Sch Arr\nSch Dep" (combined cell, two time patterns)
      col 3: "Actual Arr\nActual Dep"
      col 4: delay status
      col 5: distance / platform
    """
    url = f"{BASE_URL}/status/{train_number}"
    html = _get(url)
    if not html:
        return None

    soup = BeautifulSoup(html, "lxml")

    # Find the station table by its header row
    table = None
    for t in soup.find_all("table"):
        hdrs = [th.get_text(strip=True).lower() for th in t.find_all("th")]
        if any("station" in h for h in hdrs):
            table = t
            break

    rows_raw = table.find_all("tr") if table else soup.select("tr")

    stops = []
    seq = 1
    for row in rows_raw:
        cells = [td.get_text(separator="|", strip=True) for td in row.find_all(["td", "th"])]
        if len(cells) < 3:
            continue

        # Column 1 contains "STATION NAME (CODE)|Avg Speed: --"
        station_raw = cells[1] if len(cells) > 1 else ""
        code_match = re.search(r"\(([A-Z]{2,8})\)", station_raw)
        if not code_match:
            continue
        code = code_match.group(1)
        name = re.sub(r"\s*\(.*?\).*", "", station_raw.split("|")[0]).strip()

        # Column 2: scheduled arr/dep — two time values in one cell
        sched_raw = cells[2] if len(cells) > 2 else ""
        arr, dep = _extract_times_from_cell(sched_raw, SERVICE_DATE)

        if arr is None and dep is None:
            continue

        stops.append({
            "station_code":        code,
            "station_name":        name,
            "stop_sequence":       seq,
            "scheduled_arrival":   arr,
            "scheduled_departure": dep,
        })
        seq += 1

    return stops if stops else None


def import_schedule(app, train_number: str, stops: list[dict]) -> str | None:
    from models import db, Train, TimetableRun, TimetableEvent, Station

    with app.app_context():
        # Ensure Train record exists (required by FK)
        if not db.session.get(Train, train_number):
            db.session.add(Train(
                train_number=train_number,
                train_name=TRAIN_NAMES.get(train_number, f"Train {train_number}"),
            ))
            db.session.flush()

        # Check for existing run
        existing = TimetableRun.query.filter_by(
            train_number=train_number, service_date=SERVICE_DATE
        ).first()
        if existing:
            return existing.run_id

        run_id = str(uuid.uuid4())
        run = TimetableRun(
            run_id=run_id,
            train_number=train_number,
            service_date=SERVICE_DATE,
            run_status="scheduled",
        )
        db.session.add(run)
        db.session.flush()

        for s in stops:
            sc = s["station_code"]
            if not db.session.get(Station, sc):
                db.session.add(Station(
                    id=sc, name=s["station_name"] or sc,
                    state="Unknown", layer="corridor", priority=3, status="clear",
                ))
                db.session.flush()

            evt = TimetableEvent(
                run_id=run_id,
                station_code=sc,
                stop_sequence=s["stop_sequence"],
                scheduled_arrival=s["scheduled_arrival"],
                scheduled_departure=s["scheduled_departure"],
                actual_arrival=None,
                actual_departure=None,
                min_dwell_seconds=60,
            )
            db.session.add(evt)

        try:
            db.session.commit()
            return run_id
        except Exception as e:
            db.session.rollback()
            print(f"  [db err] {train_number}: {e}")
            return None


def run(app, train_numbers: list[str]):
    total_ok = 0
    for tn in train_numbers:
        print(f"[phase3] {tn} … ", end="", flush=True)
        stops = scrape_schedule(tn)
        time.sleep(1.0)

        if not stops:
            print("no schedule found")
            continue

        run_id = import_schedule(app, tn, stops)
        if run_id:
            print(f"{len(stops)} stops → run {run_id[:8]}…")
            total_ok += 1
        else:
            print("DB error")

    print(f"\n[phase3] Done. {total_ok}/{len(train_numbers)} trains imported.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--train", help="Comma-separated train numbers (default: all)")
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
    run(_app, trains)
