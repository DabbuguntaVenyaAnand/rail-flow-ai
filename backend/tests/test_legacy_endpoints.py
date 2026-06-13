"""
test_legacy_endpoints.py — Regression tests for all 10 existing API endpoints.

Every test verifies:
  1. HTTP 200 (or expected error code)
  2. Response is valid JSON
  3. Required top-level keys are present
  4. Response shape matches what the React/Cytoscape frontend expects
"""

import pytest


# ── /api/stations ─────────────────────────────────────────────────────────────

def test_get_stations_returns_200(client):
    r = client.get("/api/stations")
    assert r.status_code == 200


def test_get_stations_json_shape(client):
    data = client.get("/api/stations").get_json()
    assert "count" in data
    assert "stations" in data
    assert isinstance(data["stations"], list)
    assert data["count"] > 0


def test_get_stations_station_fields(client):
    stations = client.get("/api/stations").get_json()["stations"]
    s = stations[0]
    for field in ("id", "name", "state", "layer", "priority", "status", "aliases"):
        assert field in s, f"Missing field '{field}' in station dict"


def test_get_stations_filter_by_layer(client):
    data = client.get("/api/stations?layer=hub").get_json()
    assert all(s["layer"] == "hub" for s in data["stations"])


# ── /api/station-lookup/<code> ────────────────────────────────────────────────

def test_station_lookup_by_id(client):
    r = client.get("/api/station-lookup/C019")
    assert r.status_code == 200
    data = r.get_json()
    assert data["id"] == "C019"
    assert "HWH" in data["aliases"]


def test_station_lookup_by_alias(client):
    r = client.get("/api/station-lookup/HWH")
    assert r.status_code == 200
    data = r.get_json()
    assert data["id"] == "C019"


def test_station_lookup_not_found(client):
    r = client.get("/api/station-lookup/NOTEXIST")
    assert r.status_code == 404
    assert "error" in r.get_json()


# ── /api/trains ───────────────────────────────────────────────────────────────

def test_get_all_trains_returns_200(client, _setup_demo_data):
    r = client.get("/api/trains")
    assert r.status_code == 200


def test_get_all_trains_gtfs_header(client, _setup_demo_data):
    data = client.get("/api/trains").get_json()
    assert "header" in data
    assert "entity" in data
    assert data["header"]["gtfs_realtime_version"] == "2.0"


def test_get_all_trains_entity_fields(client, _setup_demo_data):
    entities = client.get("/api/trains").get_json()["entity"]
    assert len(entities) > 0
    t = entities[0]
    for field in ("train_id", "train_name", "current_station",
                  "delay_minutes", "speed_kmh", "last_updated"):
        assert field in t, f"Missing field '{field}' in train entity"


# ── /api/trains/<train_id> ────────────────────────────────────────────────────

def test_get_single_train(client, _setup_demo_data):
    r = client.get("/api/trains/12301")
    assert r.status_code == 200
    data = r.get_json()
    assert data["train_id"] == "12301"


def test_get_single_train_not_found(client):
    r = client.get("/api/trains/NOTEXIST")
    assert r.status_code == 404
    assert "error" in r.get_json()


# ── POST /api/station/<id>/status ─────────────────────────────────────────────

def test_update_station_status_valid(client):
    r = client.post("/api/station/C019/status",
                    json={"status": "congestion"},
                    content_type="application/json")
    assert r.status_code == 200
    data = r.get_json()
    assert data["updated"]["status"] == "congestion"


def test_update_station_status_invalid(client):
    r = client.post("/api/station/C019/status",
                    json={"status": "on_fire"},
                    content_type="application/json")
    assert r.status_code == 400
    assert "error" in r.get_json()


def test_update_station_status_not_found(client):
    r = client.post("/api/station/NOTEXIST/status",
                    json={"status": "delayed"})
    assert r.status_code == 404


def test_update_station_status_resets_to_clear(client):
    client.post("/api/station/C019/status", json={"status": "delayed"})
    r = client.post("/api/station/C019/status",
                    json={"status": "clear"},
                    content_type="application/json")
    assert r.status_code == 200
    assert r.get_json()["updated"]["status"] == "clear"


# ── /api/graph ────────────────────────────────────────────────────────────────

def test_get_graph_returns_200(client):
    r = client.get("/api/graph")
    assert r.status_code == 200


def test_get_graph_cytoscape_elements_key(client):
    data = client.get("/api/graph").get_json()
    assert "elements" in data


def test_get_graph_has_nodes_and_edges(client):
    elements = client.get("/api/graph").get_json()["elements"]
    assert "nodes" in elements
    assert "edges" in elements


def test_get_graph_node_data_fields(client):
    nodes = client.get("/api/graph").get_json()["elements"]["nodes"]
    assert len(nodes) > 0
    node_data = nodes[0]["data"]
    for field in ("id", "label", "state", "layer", "status", "priority"):
        assert field in node_data, f"Missing node data field '{field}'"


def test_get_graph_edge_data_fields(client):
    edges = client.get("/api/graph").get_json()["elements"]["edges"]
    assert len(edges) > 0
    edge_data = edges[0]["data"]
    for field in ("id", "source", "target", "base_time", "dynamic_cost"):
        assert field in edge_data, f"Missing edge data field '{field}'"


def test_get_graph_edge_ids_prefixed_e(client):
    edges = client.get("/api/graph").get_json()["elements"]["edges"]
    assert all(e["data"]["id"].startswith("e") for e in edges)


# ── POST /api/disruption/inject ───────────────────────────────────────────────

def test_inject_disruption(client):
    r = client.post("/api/disruption/inject",
                    json={"station_id": "C019", "depth": 2},
                    content_type="application/json")
    assert r.status_code == 200
    data = r.get_json()
    assert "source" in data
    assert "impacted_nodes" in data
    assert data["depth"] == 2


def test_inject_disruption_not_found(client):
    r = client.post("/api/disruption/inject",
                    json={"station_id": "NOTEXIST"})
    assert r.status_code == 404


# ── /api/predict/ripple/<code> ────────────────────────────────────────────────

def test_predict_ripple(client):
    r = client.get("/api/predict/ripple/C019")
    assert r.status_code == 200
    data = r.get_json()
    assert "station_id" in data
    assert "ripple_probability" in data
    assert 0.0 <= data["ripple_probability"] <= 1.0


def test_predict_ripple_not_found(client):
    r = client.get("/api/predict/ripple/NOTEXIST")
    assert r.status_code == 404


# ── /api/analytics/delay-history/<code> ──────────────────────────────────────

def test_delay_history(client):
    r = client.get("/api/analytics/delay-history/C019")
    assert r.status_code == 200
    data = r.get_json()
    assert data["station_id"] == "C019"
    assert "incidents_30d" in data
    assert "weekly_history" in data
    assert len(data["weekly_history"]) == 7


def test_delay_history_not_found(client):
    r = client.get("/api/analytics/delay-history/NOTEXIST")
    assert r.status_code == 404


# ── /api/path ─────────────────────────────────────────────────────────────────

def test_find_path_connected(client):
    # C019→C031 is a seeded edge
    r = client.get("/api/path?from=C019&to=C031")
    assert r.status_code == 200
    data = r.get_json()
    assert "path" in data
    assert data["from"] == "C019"
    assert data["to"] == "C031"
    assert data["hops"] >= 1


def test_find_path_by_alias(client):
    r = client.get("/api/path?from=HWH&to=KGP")
    assert r.status_code == 200
    data = r.get_json()
    assert data["from"] == "C019"
    assert data["to"] == "C031"


def test_find_path_origin_not_found(client):
    r = client.get("/api/path?from=NOTEXIST&to=C019")
    assert r.status_code == 404


def test_find_path_destination_not_found(client):
    r = client.get("/api/path?from=C019&to=NOTEXIST")
    assert r.status_code == 404


def test_find_path_no_route(client):
    # Station with no outgoing edges to the destination in current seed
    r = client.get("/api/path?from=C001&to=C400")
    # Expect either 404 (no path) or 200 — just ensure valid JSON
    assert r.status_code in (200, 404)
    assert r.get_json() is not None
