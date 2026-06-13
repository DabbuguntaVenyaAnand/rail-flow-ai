"""
fixtures/demo_timetable.py — Rail-Flow AI
Deterministic demo fixtures for timetable runs, events, live train states,
and backward-compatible TrainLocation rows.

All times are relative to SERVICE_DATE so tests that call load_demo_timetable()
always get the same data regardless of when they run.

Station codes used here are confirmed present in stations_seed.py:
  C019 = HWH (Howrah)
  C020 = SDAH (Sealdah)
  C031 = KGP (Kharagpur)
  C030 = TATA (Tatanagar)
  C013 = DHN (Dhanbad)
  C017 = PNBE (Patna)
  C021 = GHY (Guwahati)
  C022 = NJP (New Jalpaiguri)
"""

import uuid
from datetime import date, datetime, timezone, timedelta

SERVICE_DATE = date(2026, 6, 13)

# Fixed base reference time (midnight UTC of the service date)
_BASE = datetime(2026, 6, 13, 0, 0, 0, tzinfo=timezone.utc)


def _t(h: int, m: int = 0) -> datetime:
    """Return a fixed UTC datetime HH:MM on SERVICE_DATE."""
    return _BASE + timedelta(hours=h, minutes=m)


# Deterministic UUIDs so fixtures are idempotent across multiple runs.
RUNS = [
    {
        "run_id":       "00000001-0000-0000-0000-000000000001",
        "train_number": "12301",
        "train_name":   "Rajdhani Express",
        "stops": [
            # (station_code, arr, dep, min_dwell_s, actual_arr, actual_dep)
            ("C019", None,     _t(6, 0),  60,  None,     _t(6, 0)),
            ("C031", _t(7, 0), _t(7, 10), 120, _t(7, 5), _t(7, 15)),
            ("C030", _t(8, 30), _t(8, 40), 60, _t(8, 45), _t(8, 55)),
            ("C013", _t(10, 0), None,     0,   _t(10, 20), None),
        ],
        "live": {
            "observed_at":        _t(7, 20),
            "last_station_code":  "C031",
            "next_station_code":  "C030",
            "delay_seconds":      900,
            "speed_kmh":          87.5,
        },
    },
    {
        "run_id":       "00000001-0000-0000-0000-000000000002",
        "train_number": "12302",
        "train_name":   "Shatabdi Express",
        "stops": [
            ("C019", None,     _t(8, 0),  60,  None,     _t(8, 0)),
            ("C020", _t(8, 15), _t(8, 20), 60, _t(8, 15), _t(8, 20)),
            ("C022", _t(12, 0), None,     0,   _t(12, 0), None),
        ],
        "live": {
            "observed_at":        _t(8, 25),
            "last_station_code":  "C020",
            "next_station_code":  "C022",
            "delay_seconds":      0,
            "speed_kmh":          110.0,
        },
    },
    {
        "run_id":       "00000001-0000-0000-0000-000000000003",
        "train_number": "12303",
        "train_name":   "Duronto Express",
        "stops": [
            ("C017", None,      _t(9, 0),  90,  None,     _t(9, 5)),
            ("C013", _t(10, 30), _t(10, 40), 60, _t(10, 35), _t(10, 45)),
            ("C019", _t(13, 0), None,      0,   _t(13, 15), None),
        ],
        "live": {
            "observed_at":        _t(10, 50),
            "last_station_code":  "C013",
            "next_station_code":  "C019",
            "delay_seconds":      900,
            "speed_kmh":          95.0,
        },
    },
    {
        "run_id":       "00000001-0000-0000-0000-000000000004",
        "train_number": "12304",
        "train_name":   "Garib Rath",
        "stops": [
            ("C021", None,      _t(5, 0),  120, None,     _t(5, 0)),
            ("C022", _t(7, 30), _t(7, 40), 60,  _t(7, 30), _t(7, 40)),
            ("C019", _t(15, 0), None,      0,   _t(15, 0), None),
        ],
        "live": {
            "observed_at":        _t(7, 45),
            "last_station_code":  "C022",
            "next_station_code":  "C019",
            "delay_seconds":      0,
            "speed_kmh":          78.0,
        },
    },
    {
        "run_id":       "00000001-0000-0000-0000-000000000005",
        "train_number": "12305",
        "train_name":   "Humsafar Express",
        "stops": [
            ("C030", None,      _t(11, 0), 120, None,     _t(11, 0)),
            ("C031", _t(12, 30), _t(12, 40), 60, _t(12, 50), _t(13, 0)),
            ("C019", _t(14, 0), None,      0,   _t(14, 20), None),
        ],
        "live": {
            "observed_at":        _t(13, 5),
            "last_station_code":  "C031",
            "next_station_code":  "C019",
            "delay_seconds":      1200,
            "speed_kmh":          65.0,
        },
    },
]

# Backward-compatible TrainLocation rows for GET /api/trains.
# Fixed speed and delay; no random values.
TRAIN_LOCATIONS = [
    # (train_id, train_name, current_station, delay_min, speed_kmh, gtfs_trip_id)
    ("12301", "Rajdhani Express",  "C031",  15, 87.5,  "IR-TRIP-12301"),
    ("12302", "Shatabdi Express",  "C020",   0, 110.0, "IR-TRIP-12302"),
    ("12303", "Duronto Express",   "C013",  15, 95.0,  "IR-TRIP-12303"),
    ("12304", "Garib Rath",        "C022",   0, 78.0,  "IR-TRIP-12304"),
    ("12305", "Humsafar Express",  "C031",  20, 65.0,  "IR-TRIP-12305"),
    ("12306", "Vande Bharat",      "C019",   0, 130.0, "IR-TRIP-12306"),
    ("12307", "Tejas Express",     "C017",   5, 105.0, "IR-TRIP-12307"),
    ("12308", "Jan Shatabdi",      "C021",   0, 88.0,  "IR-TRIP-12308"),
    ("12309", "Antyodaya Express", "C030",  10, 72.0,  "IR-TRIP-12309"),
    ("12310", "Sampark Kranti",    "C013",   0, 95.0,  "IR-TRIP-12310"),
    ("12311", "Rajdhani Express",  "C020",  30, 60.0,  "IR-TRIP-12311"),
    ("12312", "Shatabdi Express",  "C022",   0, 100.0, "IR-TRIP-12312"),
    ("12313", "Duronto Express",   "C019",  45, 55.0,  "IR-TRIP-12313"),
    ("12314", "Garib Rath",        "C031",   0, 80.0,  "IR-TRIP-12314"),
    ("12315", "Humsafar Express",  "C017",  10, 90.0,  "IR-TRIP-12315"),
    ("12316", "Vande Bharat",      "C030",   0, 120.0, "IR-TRIP-12316"),
    ("12317", "Tejas Express",     "C013",   5, 98.0,  "IR-TRIP-12317"),
    ("12318", "Jan Shatabdi",      "C019",   0, 85.0,  "IR-TRIP-12318"),
    ("12319", "Antyodaya Express", "C021",  15, 70.0,  "IR-TRIP-12319"),
    ("12320", "Sampark Kranti",    "C022",   0, 92.0,  "IR-TRIP-12320"),
]

_FIXED_UPDATED = _t(7, 30)


def load_demo_timetable():
    """
    Populate Train, TimetableRun, TimetableEvent, LiveTrainState, and
    TrainLocation tables with deterministic demo data.

    Idempotent: existing rows with matching PKs are skipped.
    """
    from models import db, Train, TimetableRun, TimetableEvent, LiveTrainState, TrainLocation

    for run_def in RUNS:
        train_number = run_def["train_number"]
        train_name   = run_def["train_name"]

        if not db.session.get(Train, train_number):
            db.session.add(Train(
                train_number=train_number,
                train_name=train_name,
            ))

        run_id = run_def["run_id"]
        if not db.session.get(TimetableRun, run_id):
            db.session.add(TimetableRun(
                run_id=run_id,
                train_number=train_number,
                service_date=SERVICE_DATE,
                run_status="running",
            ))

        for seq, (sc, arr, dep, dwell, act_arr, act_dep) in enumerate(run_def["stops"], start=1):
            existing = TimetableEvent.query.filter_by(
                run_id=run_id, stop_sequence=seq
            ).first()
            if not existing:
                db.session.add(TimetableEvent(
                    run_id=run_id,
                    station_code=sc,
                    stop_sequence=seq,
                    scheduled_arrival=arr,
                    scheduled_departure=dep,
                    min_dwell_seconds=dwell,
                    actual_arrival=act_arr,
                    actual_departure=act_dep,
                ))

        live = run_def["live"]
        existing_live = LiveTrainState.query.filter_by(
            run_id=run_id, observed_at=live["observed_at"]
        ).first()
        if not existing_live:
            db.session.add(LiveTrainState(
                run_id=run_id,
                observed_at=live["observed_at"],
                last_station_code=live["last_station_code"],
                next_station_code=live["next_station_code"],
                delay_seconds=live["delay_seconds"],
                speed_kmh=live["speed_kmh"],
                source="demo",
            ))

    db.session.commit()
    load_demo_train_locations()


def load_demo_train_locations():
    """
    Populate TrainLocation for backward-compatible GET /api/trains.
    Returns the list of TrainLocation objects (creates them if absent).
    """
    from models import db, TrainLocation

    result = []
    for (tid, name, station, delay_min, speed, gtfs_id) in TRAIN_LOCATIONS:
        t = db.session.get(TrainLocation, tid)
        if not t:
            t = TrainLocation(
                train_id=tid,
                train_name=name,
                current_station=station,
                delay_minutes=delay_min,
                speed_kmh=speed,
                last_updated=_FIXED_UPDATED.replace(tzinfo=None),
                gtfs_trip_id=gtfs_id,
            )
            db.session.add(t)
        result.append(t)

    db.session.commit()
    return result
