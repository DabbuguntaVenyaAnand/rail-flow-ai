"""
fixtures/demo_disruptions.py — Rail-Flow AI
Deterministic demo disruption events.

One pre-defined train_delay disruption on train 12301 at HWH (C019).
"""

from datetime import datetime, timezone

_REPORTED_AT = datetime(2026, 6, 13, 6, 30, 0, tzinfo=timezone.utc)

DEMO_DISRUPTIONS = [
    {
        "disruption_id":          "d0000001-0000-0000-0000-000000000001",
        "disruption_type":        "train_delay",
        "station_code":           "C019",
        "connection_id":          None,
        "reported_at":            _REPORTED_AT,
        "expected_end_at":        None,
        "observed_delay_seconds": 900,
        "severity":               "medium",
        "metadata_json":          {"run_id": "00000001-0000-0000-0000-000000000001"},
        "is_active":              True,
    },
]


def load_demo_disruptions():
    """Populate disruption_events with deterministic demo data. Idempotent."""
    from models import db, DisruptionEvent

    for d in DEMO_DISRUPTIONS:
        existing = db.session.get(DisruptionEvent, d["disruption_id"])
        if not existing:
            db.session.add(DisruptionEvent(**d))

    db.session.commit()
