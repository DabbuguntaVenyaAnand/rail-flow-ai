import os
import random
import networkx as nx
from datetime import datetime
from flask import Flask, jsonify, request
from flask_cors import CORS
from models import db, Station, StationAlias, CorridorEdge, TrainLocation
from sqlalchemy.orm import joinedload
from graph_logic import RailGraph
from disruption_engine import propagate_downstream, predict_ripple, mock_delay_history

def create_app(config=None):
    app = Flask(__name__)
    CORS(app)
    app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL", "postgresql://postgres:201810@localhost:5432/rail_digital_twin")
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    db.init_app(app)

    rail_graph = RailGraph()
    with app.app_context():
        rail_graph.build_from_db()

    def resolve_station(code: str):
        code = code.strip().upper()
        station = Station.query.get(code)
        if station: return station
        alias = StationAlias.query.filter(db.func.upper(StationAlias.alias_code) == code).first()
        return alias.station if alias else None

    @app.route("/api/stations", methods=["GET"])
    def get_stations():
        stations = Station.query.options(joinedload(Station.aliases)).all()
        return jsonify({"stations": [s.to_dict() for s in stations]})

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
        edges = [{"data": {"id": f"e{e.edge_id}", "source": e.from_station_id, "target": e.to_station_id}} for e in connections]
        return jsonify({"elements": {"nodes": nodes, "edges": edges}})

    @app.route("/api/trains", methods=["GET"])
    def get_trains():
        return jsonify({"entity": [t.to_dict() for t in TrainLocation.query.all()]})

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