"""
app.py — Rail-Flow AI Flask backend
"""

import os
import random
from datetime import datetime, timedelta
from flask import Flask, jsonify, request
from flask_cors import CORS
from models import db, Station, StationAlias, CorridorEdge, TrainLocation
from graph_logic import RailGraph
from disruption_engine import propagate_downstream, predict_ripple, mock_delay_history

def _generate_mock_trains():
    """Generates localized telemetry over production station keys for live demo simulation UI."""
    sample_stations = Station.query.limit(20).all()
    if not sample_stations:
        return []
    
    train_names = ["Rajdhani Express", "Shatabdi Express", "Duronto Express", "Vande Bharat"]
    trains = []
    for i, s in enumerate(sample_stations):
        t = TrainLocation(
            train_id=12301 + i,
            train_name=random.choice(train_names),
            current_station=s.id,
            delay_minutes=random.choice([0, 5, 15, 45]),
            speed_kmh=round(random.uniform(50, 120), 1),
            last_updated=datetime.utcnow()
        )
        db.session.add(t)
        trains.append(t)
    db.session.commit()
    return trains

def create_app(config=None):
    app = Flask(__name__)
    CORS(app)

    # Standard Localhost Environment Pointer targeting your production database container
    app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv(
        "DATABASE_URL",
        "postgresql://postgres:201810@localhost:5432/rail_digital_twin"
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    if config:
        app.config.update(config)

    db.init_app(app)

    # Protected Instance Initializer (Skips db.create_all() to defend populated data rows)
    with app.app_context():
        pass

    # Build active graph matrix memory layers
    rail_graph = RailGraph()
    with app.app_context():
        rail_graph.build_from_db()

    def resolve_station(code: str):
        code = code.strip().upper()
        station = Station.query.get(code)
        if station:
            return station
        alias = StationAlias.query.filter(db.func.upper(StationAlias.alias_code) == code).first()
        return alias.station if alias else None

    # ── Routes ────────────────────────────────────────────────────────────────

    @app.route("/api/stations", methods=["GET"])
    def get_stations():
        stations = Station.query.order_by(Station.id).all()
        return jsonify({"count": len(stations), "stations": [s.to_dict() for s in stations]})

    @app.route("/api/station-lookup/<code_input>", methods=["GET"])
    def station_lookup(code_input):
        station = resolve_station(code_input)
        if not station:
            return jsonify({"error": f"No station found for code '{code_input.upper()}'."}), 404
        return jsonify(station.to_dict())

    @app.route("/api/trains", methods=["GET"])
    def get_all_trains():
        trains = TrainLocation.query.all()
        if not trains:
            trains = _generate_mock_trains()
        return jsonify({
            "header": {
                "gtfs_realtime_version": "2.0",
                "timestamp": datetime.utcnow().isoformat(),
                "incrementality": "FULL_DATASET"
            },
            "entity": [t.to_dict() for t in trains]
        })

    @app.route("/api/trains/<train_id>", methods=["GET"])
    def get_train(train_id):
        train = TrainLocation.query.get(int(train_id))
        if not train:
            return jsonify({"error": f"Train '{train_id}' not found."}), 404
        return jsonify(train.to_dict())

    @app.route("/api/station/<station_id>/status", methods=["POST"])
    def update_station_status(station_id):
        station = resolve_station(station_id)
        if not station:
            return jsonify({"error": "Station not found."}), 404
        body = request.get_json(silent=True) or {}
        new_status = body.get("status", "clear").lower()
        if new_status not in ("clear", "congestion", "delayed"):
            return jsonify({"error": "status must be clear | congestion | delayed"}), 400
        station.status = new_status
        db.session.commit()
        rail_graph.refresh_edge_costs()
        return jsonify({"updated": station.to_dict()})

    @app.route("/api/graph", methods=["GET"])
    def get_graph():
        nodes = [{"data": s.to_dict()} for s in Station.query.all()]
        edges = []
        for e in CorridorEdge.query.all():
            edges.append({
                "data": {
                    "id": f"e{e.edge_id}",
                    "source": e.from_station_id,
                    "target": e.to_station_id,
                    "base_time": float(e.base_time_min or 60.0),
                    "dynamic_cost": e.dynamic_cost,
                }
            })
        return jsonify({"elements": {"nodes": nodes, "edges": edges}})

    @app.route("/api/disruption/inject", methods=["POST"])
    def inject_disruption():
        body = request.get_json(silent=True) or {}
        station_id = body.get("station_id", "")
        depth = int(body.get("depth", 3))
        station = resolve_station(station_id)
        if not station:
            return jsonify({"error": "Station not found."}), 404
        station.status = "delayed"
        db.session.commit()
        rail_graph.refresh_edge_costs()
        impacted, hop_map = propagate_downstream(rail_graph, station.id, depth)
        return jsonify({
            "source": station.to_dict(),
            "depth": depth,
            "impacted_count": len(impacted),
            "impacted_nodes": [{"id": nid, "hop": hop_map[nid]} for nid in sorted(impacted, key=lambda x: hop_map[x])],
        })

    @app.route("/api/predict/ripple/<code_input>", methods=["GET"])
    def predict_ripple_route(code_input):
        station = resolve_station(code_input)
        if not station:
            return jsonify({"error": f"Station '{code_input}' not found."}), 404
        depth = int(request.args.get("depth", 3))
        return jsonify(predict_ripple(rail_graph, station, depth))

    @app.route("/api/analytics/delay-history/<code_input>", methods=["GET"])
    def delay_history(code_input):
        station = resolve_station(code_input)
        if not station:
            return jsonify({"error": f"Station '{code_input}' not found."}), 404
        return jsonify(mock_delay_history(station.id))

    @app.route("/api/path", methods=["GET"])
    def find_path():
        from_code = request.args.get("from", "")
        to_code = request.args.get("to", "")
        origin = resolve_station(from_code)
        destination = resolve_station(to_code)
        if not origin or not destination:
            return jsonify({"error": "Invalid origin or destination codes."}), 404
        
        path, total_cost = rail_graph.astar(origin.id, destination.id)
        if path is None:
            return jsonify({"error": "No path found between selected coordinates."}), 404
            
        path_details = []
        for node_id in path:
            s = Station.query.get(node_id)
            if s:
                path_details.append({"id": s.id, "name": s.name, "status": s.status})
        return jsonify({
            "from": origin.id,
            "to": destination.id,
            "hops": len(path) - 1,
            "total_cost": round(total_cost, 1),
            "path": path_details,
        })

    return app

if __name__ == "__main__":
    app = create_app()
    app.run(debug=True, port=5000)