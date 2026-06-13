"""
graph_logic.py — Rail-Flow AI
Time-Extended Graph model with A* pathfinding.
"""

import heapq
import math
from typing import Optional

TRAFFIC_DELAY = {"clear": 0, "congestion": 15, "delayed": 45}
MAINT_PENALTY  = {"clear": 0, "congestion":  5, "delayed": 10}

class RailGraph:
    def __init__(self):
        self._adj: dict[str, list[tuple[str, float, int]]] = {}
        self._cost_cache: dict[tuple[str, str], float] = {}
        self._status: dict[str, str] = {}

    def build_from_db(self):
        """Load edges and station statuses directly from populated tables."""
        from models import CorridorEdge, Station
        self._adj.clear()
        self._cost_cache.clear()

        for s in Station.query.all():
            self._status[s.id] = s.status or "clear"
            self._adj.setdefault(s.id, [])

        for e in CorridorEdge.query.all():
            base_time = float(e.base_time_min or 60.0)
            self._adj.setdefault(e.from_station_id, []).append((e.to_station_id, base_time, e.edge_id))
            self._adj.setdefault(e.to_station_id, []).append((e.from_station_id, base_time, e.edge_id))

        self._build_cost_cache()

    def _build_cost_cache(self):
        for frm, neighbours in self._adj.items():
            for (to, base_time, _) in neighbours:
                td = TRAFFIC_DELAY.get(self._status.get(frm, "clear"), 0)
                mp = MAINT_PENALTY.get(self._status.get(to,  "clear"), 0)
                self._cost_cache[(frm, to)] = base_time + td + mp

    def refresh_edge_costs(self):
        from models import Station
        for s in Station.query.all():
            self._status[s.id] = s.status or "clear"
        self._build_cost_cache()

    def astar(self, origin_id: str, dest_id: str) -> tuple[Optional[list[str]], float]:
        if origin_id not in self._adj or dest_id not in self._adj:
            return None, math.inf

        open_heap: list[tuple[float, float, str]] = []
        heapq.heappush(open_heap, (0.0, 0.0, origin_id))

        came_from: dict[str, Optional[str]] = {origin_id: None}
        g_score: dict[str, float] = {origin_id: 0.0}

        while open_heap:
            _, g, current = heapq.heappop(open_heap)

            if current == dest_id:
                return self._reconstruct_path(came_from, dest_id), g

            if g > g_score.get(current, math.inf):
                continue

            for (neighbour, default_base, _) in self._adj.get(current, []):
                edge_cost = self._cost_cache.get((current, neighbour), default_base)
                tentative_g = g_score[current] + edge_cost

                if tentative_g < g_score.get(neighbour, math.inf):
                    g_score[neighbour] = tentative_g
                    came_from[neighbour] = current
                    h = self._heuristic(neighbour, dest_id)
                    heapq.heappush(open_heap, (tentative_g + h, tentative_g, neighbour))

        return None, math.inf

    def _heuristic(self, node_id: str, goal_id: str) -> float:
        return 0.0

    @staticmethod
    def _reconstruct_path(came_from: dict[str, Optional[str]], dest_id: str) -> list[str]:
        path = []
        current: Optional[str] = dest_id
        while current is not None:
            path.append(current)
            current = came_from[current]
        path.reverse()
        return path

    def neighbours(self, node_id: str) -> list[str]:
        return [n for (n, _, _) in self._adj.get(node_id, [])]

    def edge_cost(self, from_id: str, to_id: str) -> float:
        return self._cost_cache.get((from_id, to_id), math.inf)

    def node_count(self) -> int:
        return len(self._adj)

    def edge_count(self) -> int:
        return sum(len(v) for v in self._adj.values())