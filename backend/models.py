"""
models.py — Rail-Flow AI
SQLAlchemy ORM models for the 500-station demo network.
"""

from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


# ─────────────────────────────────────────────
# Core station record
# ─────────────────────────────────────────────
class Station(db.Model):
    __tablename__ = "stations"

    id          = db.Column(db.String(10),  primary_key=True)   # e.g. C001 / N001
    name        = db.Column(db.String(120), nullable=False)
    state       = db.Column(db.String(60),  nullable=False)
    division    = db.Column(db.String(20),  nullable=True)       # NULL for hub layer
    zone        = db.Column(db.String(10),  nullable=True)
    category    = db.Column(db.String(5),   nullable=True)       # A1 / A / B / C / D
    layer       = db.Column(db.String(20),  nullable=False,
                            default="corridor")                  # corridor | hub
    priority    = db.Column(db.Integer,     nullable=False,
                            default=3)                           # 1=critical … 5=low
    # Runtime state (not persisted; refreshed by mock orchestrator)
    status      = db.Column(db.String(20),  nullable=False,
                            default="clear")                     # clear | congestion | delayed

    aliases     = db.relationship("StationAlias", back_populates="station",
                                  cascade="all, delete-orphan")
    train_locs  = db.relationship("TrainLocation", back_populates="station",
                                  cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "id":       self.id,
            "name":     self.name,
            "state":    self.state,
            "division": self.division,
            "zone":     self.zone,
            "category": self.category,
            "layer":    self.layer,
            "priority": self.priority,
            "status":   self.status,
            "aliases":  [a.alias_code for a in self.aliases],
        }


# ─────────────────────────────────────────────
# Alias / old-code mapping engine
# ─────────────────────────────────────────────
class StationAlias(db.Model):
    __tablename__ = "station_aliases"

    alias_id    = db.Column(db.Integer,    primary_key=True, autoincrement=True)
    station_id  = db.Column(db.String(10), db.ForeignKey("stations.id",
                            ondelete="CASCADE"), nullable=False)
    alias_code  = db.Column(db.String(20), nullable=False, unique=True, index=True)
    alias_type  = db.Column(db.String(30), nullable=False,
                            default="operational")  # operational | legacy | display

    station     = db.relationship("Station", back_populates="aliases")

    def to_dict(self):
        return {
            "alias_id":   self.alias_id,
            "station_id": self.station_id,
            "alias_code": self.alias_code,
            "alias_type": self.alias_type,
        }


# ─────────────────────────────────────────────
# Graph edges (corridor connections)
# ─────────────────────────────────────────────
class CorridorEdge(db.Model):
    __tablename__ = "corridor_edges"

    edge_id         = db.Column(db.Integer,    primary_key=True, autoincrement=True)
    from_station_id = db.Column(db.String(10), db.ForeignKey("stations.id"), nullable=False)
    to_station_id   = db.Column(db.String(10), db.ForeignKey("stations.id"), nullable=False)
    base_time_min   = db.Column(db.Float,      nullable=False, default=60.0)   # minutes
    distance_km     = db.Column(db.Float,      nullable=True)
    is_bidirectional= db.Column(db.Boolean,    nullable=False, default=True)

    from_station    = db.relationship("Station", foreign_keys=[from_station_id])
    to_station      = db.relationship("Station", foreign_keys=[to_station_id])

    @property
    def dynamic_cost(self):
        """
        Cost = Base_Time + Traffic_Delay + Maint_Penalty
        Reads live status from linked stations to adjust.
        """
        traffic_delay  = {"clear": 0, "congestion": 15, "delayed": 45}.get(
                            self.from_station.status, 0)
        maint_penalty  = {"clear": 0, "congestion": 5,  "delayed": 10}.get(
                            self.to_station.status,   0)
        return self.base_time_min + traffic_delay + maint_penalty

    def to_dict(self):
        return {
            "edge_id":          self.edge_id,
            "from":             self.from_station_id,
            "to":               self.to_station_id,
            "base_time_min":    self.base_time_min,
            "dynamic_cost":     self.dynamic_cost,
            "distance_km":      self.distance_km,
            "bidirectional":    self.is_bidirectional,
        }


# ─────────────────────────────────────────────
# Real-time train telemetry
# ─────────────────────────────────────────────
class TrainLocation(db.Model):
    __tablename__ = "train_locations"

    train_id        = db.Column(db.String(20), primary_key=True)   # e.g. 12301
    train_name      = db.Column(db.String(100), nullable=True)
    current_station = db.Column(db.String(10),  db.ForeignKey("stations.id"), nullable=True)
    delay_minutes   = db.Column(db.Integer,     nullable=False, default=0)
    speed_kmh       = db.Column(db.Float,       nullable=True)
    last_updated    = db.Column(db.DateTime,    nullable=False, default=datetime.utcnow)
    gtfs_trip_id    = db.Column(db.String(40),  nullable=True)    # GTFS compliance field

    station         = db.relationship("Station", back_populates="train_locs")

    def to_dict(self):
        return {
            "train_id":        self.train_id,
            "train_name":      self.train_name,
            "current_station": self.current_station,
            "delay_minutes":   self.delay_minutes,
            "speed_kmh":       self.speed_kmh,
            "last_updated":    self.last_updated.isoformat(),
            "gtfs_trip_id":    self.gtfs_trip_id,
        }
