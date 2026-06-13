"""
disruption_engine.py — Rail-Flow AI
"""

import random
from datetime import datetime, timedelta
from graph_logic import RailGraph

def propagate_downstream(rail_graph: RailGraph, start_id: str, max_depth: int = 3) -> tuple[set[str], dict[str, int]]:
    impacted: set[str] = set()
    hop_map: dict[str, int] = {}
    queue: list[tuple[str, int]] = [(start_id, 0)]
    visited: set[str] = {start_id}

    while queue:
        current, depth = queue.pop(0)
        if depth >= max_depth:
            continue
        for neighbour in rail_graph.neighbours(current):
            if neighbour in visited:
                continue
            visited.add(neighbour)
            impacted.add(neighbour)
            hop_map[neighbour] = depth + 1
            queue.append((neighbour, depth + 1))

    impacted.discard(start_id)
    return impacted, hop_map

def predict_ripple(rail_graph: RailGraph, station, max_depth: int = 3) -> dict:
    out_degree = len(rail_graph.neighbours(station.id))
    score = 0.25

    if out_degree >= 3:
        score += 0.3
    elif out_degree >= 1:
        score += 0.15

    stressed = sum(
        1 for n in rail_graph.neighbours(station.id)
        if rail_graph._status.get(n, "clear") != "clear"
    )
    score += min(0.2, stressed * 0.1)
    score = min(0.95, max(0.05, score))

    impacted, hop_map = propagate_downstream(rail_graph, station.id, max_depth)

    return {
        "station_id": station.id,
        "ripple_probability": round(score, 2),
        "will_ripple": score >= 0.5,
        "predicted_impact_count": len(impacted),
        "impacted_nodes": [
            {"id": nid, "hop": hop_map[nid], "status": rail_graph._status.get(nid, "clear")}
            for nid in sorted(impacted, key=lambda x: hop_map[x])
        ],
        "resolution_estimate": "Expect cascade — recommend rerouting" if score >= 0.5 else "Likely contained within local corridor",
    }

def mock_delay_history(station_id: str) -> dict:
    rng = random.Random(hash(station_id) % 2**32)
    incidents = rng.randint(2, 14)
    avg_delay = rng.randint(5, 40)
    history = []
    for i in range(7):
        day = datetime.utcnow() - timedelta(days=i)
        history.append({
            "date": day.strftime("%Y-%m-%d"),
            "incidents": rng.randint(0, 3),
            "avg_delay_min": rng.randint(0, avg_delay + 10),
        })

    return {
        "station_id": station_id,
        "incidents_30d": incidents,
        "avg_delay_min": avg_delay,
        "max_delay_min": avg_delay + rng.randint(10, 45),
        "ripple_probability": round(rng.uniform(0.3, 0.85), 2),
        "resolution_rate": round(rng.uniform(0.55, 0.92), 2),
        "weekly_history": history,
    }