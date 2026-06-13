"""
test_rescheduling_api.py — Integration tests for POST /api/v1/rescheduling/compute
and GET /api/v1/rescheduling/latest.
"""

from __future__ import annotations

import json

import pytest


def test_compute_returns_200(client, _setup_demo_data):
    """POST /api/v1/rescheduling/compute returns 200 with a valid response."""
    payload = {
        "trigger_type": "manual",
        "t0": "2026-06-13T05:00:00+00:00",
        "policy": "greedy",
        "horizon_minutes": 600,
    }
    r = client.post(
        "/api/v1/rescheduling/compute",
        data=json.dumps(payload),
        content_type="application/json",
    )
    assert r.status_code == 200
    data = r.get_json()
    assert "status" in data
    assert "objective_before" in data
    assert "objective_after" in data
    assert "actions" in data
    assert "conflicts_detected" in data


def test_compute_beam_search(client, _setup_demo_data):
    """beam_search policy also returns a valid response."""
    payload = {
        "trigger_type": "manual",
        "t0": "2026-06-13T05:00:00+00:00",
        "policy": "beam_search",
        "horizon_minutes": 600,
    }
    r = client.post(
        "/api/v1/rescheduling/compute",
        data=json.dumps(payload),
        content_type="application/json",
    )
    assert r.status_code == 200
    data = r.get_json()
    assert data["status"] in ("success", "partial", "no_runs_in_horizon")


def test_compute_invalid_t0(client, _setup_demo_data):
    """Invalid t0 format returns 400."""
    r = client.post(
        "/api/v1/rescheduling/compute",
        data=json.dumps({"t0": "not-a-datetime"}),
        content_type="application/json",
    )
    assert r.status_code == 400
    assert "error" in r.get_json()


def test_compute_no_body_uses_defaults(client, _setup_demo_data):
    """Missing body should not crash — defaults kick in."""
    r = client.post(
        "/api/v1/rescheduling/compute",
        data="{}",
        content_type="application/json",
    )
    assert r.status_code == 200


def test_latest_after_compute(client, _setup_demo_data):
    """GET /api/v1/rescheduling/latest returns the run just created."""
    # First create a run
    client.post(
        "/api/v1/rescheduling/compute",
        data=json.dumps({
            "t0": "2026-06-13T05:00:00+00:00",
            "policy": "greedy",
            "horizon_minutes": 600,
        }),
        content_type="application/json",
    )

    r = client.get("/api/v1/rescheduling/latest")
    assert r.status_code == 200
    data = r.get_json()
    assert "rescheduling_run_id" in data
    assert "actions" in data


def test_latest_returns_valid_response_shape(client, _setup_demo_data):
    """
    GET /api/v1/rescheduling/latest returns either 404 (no runs yet) or 200
    with a well-formed response.  Both outcomes are valid since this test
    shares the session-scoped DB with other compute tests.
    """
    r = client.get("/api/v1/rescheduling/latest")
    assert r.status_code in (200, 404)
    data = r.get_json()
    if r.status_code == 200:
        assert "rescheduling_run_id" in data
        assert "actions" in data
    else:
        assert "error" in data


def test_compute_idempotent_objective(client, _setup_demo_data):
    """
    Running compute twice with the same t0 should produce the same
    objective_before value (deterministic snapshot).
    """
    payload = {
        "t0": "2026-06-13T05:00:00+00:00",
        "policy": "greedy",
        "horizon_minutes": 600,
    }
    r1 = client.post(
        "/api/v1/rescheduling/compute",
        data=json.dumps(payload),
        content_type="application/json",
    ).get_json()

    r2 = client.post(
        "/api/v1/rescheduling/compute",
        data=json.dumps(payload),
        content_type="application/json",
    ).get_json()

    assert r1["objective_before"] == pytest.approx(r2["objective_before"]), (
        "objective_before must be deterministic for the same t0"
    )
