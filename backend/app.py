import os
import sys
import random
import networkx as nx
from datetime import datetime, timezone
from flask import Flask, jsonify, request
from flask_cors import CORS
from flask_migrate import Migrate

from config import Config
from models import db, Station, StationAlias, CorridorEdge, TrainLocation
from sqlalchemy.orm import joinedload
from graph_logic import RailGraph
from disruption_engine import propagate_downstream, predict_ripple, mock_delay_history

# ── Seed helpers ──────────────────────────────────────────────────────────────

def _seed_stations():
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "data"))
    from stations_seed import CORRIDOR_STATIONS, HUB_STATIONS

    priority_map = {"A1": 1, "A": 1, "B": 2, "C": 3, "D": 4}

    for (node_id, alias, name, state, div, zone, cat) in CORRIDOR_STATIONS:
        s = Station(
            id=node_id, name=name, state=state,
            division=div, zone=zone, category=cat,
            layer="corridor",
            priority=priority_map.get(cat, 3)
        )
        db.session.add(s)
        db.session.add(StationAlias(
            station_id=node_id, alias_code=alias, alias_type="operational"
        ))
        db.session.add(StationAlias(
            station_id=node_id, alias_code=node_id, alias_type="display"
        ))

    for (node_id, alias, name, state) in HUB_STATIONS:
        s = Station(
            id=node_id, name=name, state=state,
            layer="hub", priority=1
        )
        db.session.add(s)
        existing = StationAlias.query.filter_by(alias_code=alias).first()
        if not existing:
            db.session.add(StationAlias(
                station_id=node_id, alias_code=alias, alias_type="operational"
            ))


def _seed_edges():
    sample_edges = [
        ("C019", "C020", 45,  15),
        ("C019", "C031", 120, 80),
        ("C031", "C030", 90,  60),
        ("C030", "C127", 150, 110),
        ("C013", "C062", 30,  25),
        ("C017", "C014", 120, 98),
        ("C021", "C022", 180, 140),
        ("C082", "C084", 60,  45),
        ("C084", "C019", 90,  65),
    ]
    for (frm, to, base, dist) in sample_edges:
        db.session.add(CorridorEdge(
            from_station_id=frm, to_station_id=to,
            base_time_min=base,
            is_bidirectional=True
        ))


def _seed_if_empty():
    if Station.query.count() > 0:
        return
    _seed_stations()
    _seed_edges()
    db.session.commit()
    print("[Rail-Flow] Database seeded with stations.")


# ── App factory ───────────────────────────────────────────────────────────────

def create_app(config_overrides=None):
    app = Flask(__name__)
    CORS(app)
    
    app.config.from_object(Config)
    if not os.environ.get("DATABASE_URL"):
        app.config["SQLALCHEMY_DATABASE_URI"] = "postgresql://postgres:201810@localhost:5432/rail_digital_twin"
        
    if config_overrides:
        app.config.update(config_overrides)
        
    db.init_app(app)
    Migrate(app, db)

    demo_mode = app.config.get("DEMO_MODE", True)

    with app.app_context():
        if app.config.get("TESTING") or app.config["SQLALCHEMY_DATABASE_URI"].startswith("sqlite"):
            db.create_all()
            try:
                _seed_if_empty()
            except Exception as e:
                print(f"Error seeding DB: {e}")
                pass

    rail_graph = RailGraph()
    with app.app_context():
        try:
            rail_graph.build_from_db()
        except Exception:
            # Tables don't exist yet (pre-migration)
            pass

    # ── Register Blueprints ──────────────────────────────────────────────────
    from api.rescheduling_routes import rescheduling_bp
    app.register_blueprint(rescheduling_bp)

    # ── Rolling-horizon background worker (opt-in) ───────────────────────────
    if app.config.get("ROLLING_HORIZON_ENABLED", False):
        from rescheduling.rolling_horizon import RollingHorizonService
        _rolling_svc = RollingHorizonService(
            horizon_minutes=app.config.get("HORIZON_MIN", 60),
            commit_window_minutes=app.config.get("COMMIT_WINDOW_MIN", 10),
            policy_name=app.config.get("POLICY_BACKEND", "beam_search"),
            refresh_seconds=app.config.get("ROLLING_REFRESH_SECONDS", 60),
        )
        _rolling_svc.start_background_worker(app)

        @app.teardown_appcontext
        def _stop_rolling_horizon(exc):
            _rolling_svc.stop()

    # ── CLI commands ─────────────────────────────────────────────────────────
    @app.cli.command("seed-demo")
    def seed_demo_command():
        """Load deterministic demo fixtures (timetable, live states, disruptions)."""
        from fixtures.demo_timetable import load_demo_timetable
        from fixtures.demo_disruptions import load_demo_disruptions
        with app.app_context():
            load_demo_timetable()
            load_demo_disruptions()
        print("[Rail-Flow] Demo fixtures loaded.")

    # ── Helper resolution ────────────────────────────────────────────────────
    def resolve_station(code: str):
        code = code.strip().upper()
        station = db.session.get(Station, code)
        if station: return station
        alias = StationAlias.query.filter(db.func.upper(StationAlias.alias_code) == code).first()
        return alias.station if alias else None

    # ── Legacy endpoints ─────────────────────────────────────────────────────
    @app.route("/api/stations", methods=["GET"])
    def get_stations():
        query = Station.query.options(joinedload(Station.aliases))
        if layer := request.args.get("layer"):
            query = query.filter_by(layer=layer.lower())
        if state := request.args.get("state"):
            query = query.filter(Station.state.ilike(f"%{state}%"))
        stations = query.order_by(Station.id).all()
        return jsonify({"count": len(stations), "stations": [s.to_dict() for s in stations]})

    @app.route("/api/station-lookup/<code_input>", methods=["GET"])
    def station_lookup(code_input):
        station = resolve_station(code_input)
        return jsonify(station.to_dict()) if station else (jsonify({"error": "Not found"}), 404)

    @app.route("/api/graph", methods=["GET"])
    def get_graph():
        # Only return core backbone and hub stations to avoid visual clutter and browser lag
        stations = Station.query.filter(Station.state.isnot(None)).options(joinedload(Station.aliases)).all()
        core_ids = {s.id for s in stations}
        connections = CorridorEdge.query.filter(
            CorridorEdge.from_station_id.in_(core_ids),
            CorridorEdge.to_station_id.in_(core_ids)
        ).all()
        G = nx.Graph()
        for s in stations: G.add_node(s.id)
        for e in connections: G.add_edge(e.from_station_id, e.to_station_id)
        pos = nx.random_layout(G, seed=42) 
        
        nodes = [{"data": s.to_dict(), "position": {'x': float(pos[s.id][0]*1000), 'y': float(pos[s.id][1]*1000)}} for s in stations]
        
        edges = []
        for e in connections:
            edges.append({
                "data": {
                    "id": f"e{e.edge_id}",
                    "source": e.from_station_id,
                    "target": e.to_station_id,
                    "base_time": e.base_time_min,
                    "dynamic_cost": e.dynamic_cost
                }
            })
        return jsonify({"elements": {"nodes": nodes, "edges": edges}})

    @app.route("/api/trains", methods=["GET"])
    def get_trains():
        trains = TrainLocation.query.all()
        if not trains and demo_mode:
            from fixtures.demo_timetable import load_demo_train_locations
            trains = load_demo_train_locations()
        return jsonify({
            "header": {
                "gtfs_realtime_version": "2.0",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "incrementality": "FULL_DATASET",
            },
            "entity": [t.to_dict() for t in trains],
        })

    @app.route("/api/trains/<train_id>", methods=["GET"])
    def get_train(train_id):
        train = db.session.get(TrainLocation, train_id)
        if not train:
            return jsonify({"error": f"Train '{train_id}' not found."}), 404
        return jsonify(train.to_dict())

    @app.route("/api/station/<id>/status", methods=["POST"])
    def update_station_status(id):
        station = resolve_station(id)
        if not station:
            return jsonify({"error": "Station not found"}), 404
        data = request.get_json() or {}
        new_status = data.get("status")
        if new_status not in ["clear", "congestion", "delayed"]:
            return jsonify({"error": "Invalid status"}), 400
        station.status = new_status
        db.session.commit()
        rail_graph.refresh_edge_costs()
        return jsonify({"updated": station.to_dict()})

    @app.route("/api/analytics/delay-history/<id>", methods=["GET"])
    def get_delay_history(id):
        station = resolve_station(id)
        if not station:
            return jsonify({"error": "Station not found"}), 404
        return jsonify(mock_delay_history(station.id))

    @app.route("/api/predict/ripple/<id>", methods=["GET"])
    def get_ripple_prediction(id):
        station = resolve_station(id)
        if not station:
            return jsonify({"error": "Station not found"}), 404
        depth = int(request.args.get("depth", 3))
        return jsonify(predict_ripple(rail_graph, station, depth))

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
            "impacted_nodes": [
                {"id": nid, "hop": hop_map[nid]}
                for nid in sorted(impacted, key=lambda x: hop_map[x])
            ],
        })

    @app.route("/api/path", methods=["GET"])
    def find_path():
        origin = resolve_station(request.args.get("from", ""))
        destination = resolve_station(request.args.get("to", ""))
        if not origin or not destination:
            return jsonify({"error": "Invalid origin or destination station"}), 404
        path, cost = rail_graph.astar(origin.id, destination.id)
        if not path:
            return jsonify({"error": "No path found between selected stations"}), 404
            
        path_nodes = []
        disrupted_nodes = []
        for nid in path:
            station = Station.query.get(nid)
            status = station.status if station else "clear"
            if status != "clear":
                disrupted_nodes.append(nid)
            path_nodes.append({
                "id": nid,
                "name": station.name if station else nid,
                "status": status
            })
            
        response_data = {
            "from": origin.id,
            "to": destination.id,
            "path": path_nodes,
            "total_cost": round(cost, 2),
            "hops": len(path) - 1
        }

        # If any station along the path is disrupted, compute a bypass path
        if disrupted_nodes:
            bypass_path, bypass_cost = rail_graph.astar(origin.id, destination.id, avoid_nodes=set(disrupted_nodes))
            if bypass_path:
                bypass_nodes = []
                for nid in bypass_path:
                    station = Station.query.get(nid)
                    bypass_nodes.append({
                        "id": nid,
                        "name": station.name if station else nid,
                        "status": station.status if station else "clear"
                    })
                response_data["alternative_path"] = bypass_nodes
                response_data["alternative_cost"] = round(bypass_cost, 2)
                response_data["disrupted_stations"] = [
                    (Station.query.get(nid).name or nid) for nid in disrupted_nodes
                ]

        return jsonify(response_data)

    return app

if __name__ == "__main__":
    create_app().run(debug=True, port=5000)