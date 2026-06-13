"""
test_no_random_in_production.py
Verify that repeated calls to production endpoints return identical JSON,
proving no random values are generated per-request.
"""

import pytest


def _sorted_stable(obj):
    """Recursively sort lists of dicts so comparison is order-independent."""
    if isinstance(obj, dict):
        return {k: _sorted_stable(v) for k, v in sorted(obj.items())}
    if isinstance(obj, list):
        try:
            return sorted(_sorted_stable(i) for i in obj)
        except TypeError:
            return [_sorted_stable(i) for i in obj]
    return obj


def test_trains_deterministic(client, _setup_demo_data):
    r1 = client.get("/api/trains").get_json()
    r2 = client.get("/api/trains").get_json()
    # Compare entities without the timestamp header field
    e1 = _sorted_stable(r1["entity"])
    e2 = _sorted_stable(r2["entity"])
    assert e1 == e2, "GET /api/trains returned different entity lists on two calls"


def test_delay_history_deterministic(client):
    for code in ("C019", "C013", "C031"):
        r1 = client.get(f"/api/analytics/delay-history/{code}").get_json()
        r2 = client.get(f"/api/analytics/delay-history/{code}").get_json()
        assert r1 == r2, (
            f"GET /api/analytics/delay-history/{code} returned "
            f"different results on two calls"
        )


def test_ripple_deterministic(client):
    r1 = client.get("/api/predict/ripple/C019").get_json()
    r2 = client.get("/api/predict/ripple/C019").get_json()
    assert r1 == r2, "GET /api/predict/ripple/C019 returned different results on two calls"


def test_graph_deterministic(client):
    e1 = client.get("/api/graph").get_json()["elements"]
    e2 = client.get("/api/graph").get_json()["elements"]
    n1 = _sorted_stable(e1["nodes"])
    n2 = _sorted_stable(e2["nodes"])
    assert n1 == n2, "GET /api/graph nodes differ between calls"


def test_station_lookup_deterministic(client):
    r1 = client.get("/api/station-lookup/HWH").get_json()
    r2 = client.get("/api/station-lookup/HWH").get_json()
    assert r1 == r2, "GET /api/station-lookup/HWH returned different results"
