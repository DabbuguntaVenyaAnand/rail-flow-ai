"""
models.py — Rail-Flow AI (PostgreSQL Mapped)
"""

from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

# ─────────────────────────────────────────────
# Stations (Maps to 'stations' table)
# ─────────────────────────────────────────────
class Station(db.Model):
    __tablename__ = "stations"

    id = db.Column("station_code", db.String(20), primary_key=True)
    name = db.Column("station_name", db.String(100), nullable=False)
    
    # Custom simulation state column added via manual patch command
    status = db.Column(db.String(20), nullable=False, default="clear")

    aliases = db.relationship("StationAlias", back_populates="station", cascade="all, delete-orphan")
    train_locs = db.relationship("TrainLocation", back_populates="station", cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "state": "Unknown",      # Fallback fields matching your previous mock format
            "division": "Unknown",
            "zone": "Unknown",
            "category": "Standard",
            "layer": "corridor",
            "priority": 3,
            "status": self.status,
            "aliases": [a.alias_code for a in self.aliases],
        }

# ─────────────────────────────────────────────
# Station Aliases (Maps to 'station_aliases' table)
# ─────────────────────────────────────────────
class StationAlias(db.Model):
    __tablename__ = "station_aliases"

    alias_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    station_id = db.Column("station_code", db.String(20), db.ForeignKey("stations.station_code", ondelete="CASCADE"), nullable=False)
    alias_code = db.Column(db.String(20), nullable=False, unique=True, index=True)
    alias_type = db.Column(db.String(30), nullable=False, default="operational")

    station = db.relationship("Station", back_populates="aliases")

    def to_dict(self):
        return {
            "alias_id": self.alias_id,
            "station_id": self.station_id,
            "alias_code": self.alias_code,
            "alias_type": self.alias_type,
        }

# ─────────────────────────────────────────────
# Graph Edges (Maps to 'station_connections' table)
# ─────────────────────────────────────────────
class CorridorEdge(db.Model):
    __tablename__ = "station_connections"

    edge_id = db.Column("connection_id", db.Integer, primary_key=True)
    from_station_id = db.Column("source_station", db.String(20), db.ForeignKey("stations.station_code"), nullable=False)
    to_station_id = db.Column("destination_station", db.String(20), db.ForeignKey("stations.station_code"), nullable=False)
    base_time_min = db.Column("distance_km", db.Numeric(10, 2), nullable=False, default=60.0)

    from_station = db.relationship("Station", foreign_keys=[from_station_id])
    to_station = db.relationship("Station", foreign_keys=[to_station_id])

    @property
    def is_bidirectional(self):
        return True

    @property
    def dynamic_cost(self):
        """Cost = Base_Distance/Time + Traffic_Delay + Maint_Penalty"""
        traffic_delay = {"clear": 0, "congestion": 15, "delayed": 45}.get(self.from_station.status, 0)
        maint_penalty = {"clear": 0, "congestion": 5, "delayed": 10}.get(self.to_station.status, 0)
        return float(self.base_time_min or 60.0) + traffic_delay + maint_penalty

    def to_dict(self):
        return {
            "edge_id": self.edge_id,
            "from": self.from_station_id,
            "to": self.to_station_id,
            "base_time": float(self.base_time_min or 60.0),
            "dynamic_cost": self.dynamic_cost,
            "bidirectional": True,
        }

# ─────────────────────────────────────────────
# Train Telemetry (Maps to 'trains' table)
# ─────────────────────────────────────────────
class TrainLocation(db.Model):
    __tablename__ = "trains"

    train_id = db.Column("train_number", db.BigInteger, primary_key=True)
    train_name = db.Column(db.String(200), nullable=True)
    
    # Virtual in-memory simulation attributes mapped out of core tables
    current_station = db.Column(db.String(20), db.ForeignKey("stations.station_code"), nullable=True)
    delay_minutes = db.Column(db.Integer, nullable=False, default=0)
    speed_kmh = db.Column(db.Float, nullable=True, default=70.0)
    last_updated = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    gtfs_trip_id = db.Column(db.String(40), nullable=True)

    station = db.relationship("Station", back_populates="train_locs")

    def to_dict(self):
        return {
            "train_id": str(self.train_id),
            "train_name": self.train_name,
            "current_station": self.current_station,
            "delay_minutes": self.delay_minutes,
            "speed_kmh": self.speed_kmh,
            "last_updated": self.last_updated.isoformat() if self.last_updated else datetime.utcnow().isoformat(),
            "gtfs_trip_id": self.gtfs_trip_id or f"IR-TRIP-{self.train_id}",
        }