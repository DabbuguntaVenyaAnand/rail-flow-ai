"""
models.py — Rail-Flow AI (Merged HSR-RailFlow)
"""

import uuid
from datetime import datetime, timezone
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ══════════════════════════════════════════════════════════════════════════════
# EXISTING MODELS — mapped to PostgreSQL database schema
# ══════════════════════════════════════════════════════════════════════════════

class Station(db.Model):
    __tablename__ = "stations"

    id          = db.Column("station_code", db.String(20),  primary_key=True)
    name        = db.Column("station_name", db.String(120), nullable=False)
    state       = db.Column(db.String(60),  nullable=True)
    division    = db.Column(db.String(30),  nullable=True)
    zone        = db.Column(db.String(30),  nullable=True)
    category    = db.Column(db.String(20),  nullable=True)
    layer       = db.Column(db.String(20),  nullable=False, default="corridor")
    priority    = db.Column(db.Integer,     nullable=False, default=3)
    status      = db.Column(db.String(20),  nullable=False, default="clear")

    aliases     = db.relationship("StationAlias", back_populates="station",
                                  cascade="all, delete-orphan")
    train_locs  = db.relationship("TrainLocation", back_populates="station",
                                  cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "id":       self.id,
            "name":     self.name,
            "label":    self.id,
            "state":    self.state or "Unknown",
            "division": self.division or "Unknown",
            "zone":     self.zone or "Unknown",
            "category": self.category or "Standard",
            "layer":    self.layer or "corridor",
            "priority": self.priority,
            "status":   self.status,
            "aliases":  [a.alias_code for a in self.aliases],
        }


class StationAlias(db.Model):
    __tablename__ = "station_aliases"

    alias_id    = db.Column(db.Integer,    primary_key=True, autoincrement=True)
    station_id  = db.Column("station_code", db.String(20), db.ForeignKey("stations.station_code",
                            ondelete="CASCADE"), nullable=False)
    alias_code  = db.Column(db.String(20), nullable=False, unique=True, index=True)
    alias_type  = db.Column(db.String(30), nullable=False, default="operational")

    station     = db.relationship("Station", back_populates="aliases")

    def to_dict(self):
        return {
            "alias_id":   self.alias_id,
            "station_id": self.station_id,
            "alias_code": self.alias_code,
            "alias_type": self.alias_type,
        }


class CorridorEdge(db.Model):
    __tablename__ = "station_connections"

    edge_id             = db.Column("connection_id", db.Integer,    primary_key=True, autoincrement=True)
    from_station_id     = db.Column("source_station", db.String(20), db.ForeignKey("stations.station_code"), nullable=False)
    to_station_id       = db.Column("destination_station", db.String(20), db.ForeignKey("stations.station_code"), nullable=False)
    _base_time_min      = db.Column("distance_km", db.Float,      nullable=True, default=60.0)
    is_bidirectional    = db.Column(db.Boolean,    nullable=False, default=True)

    # Operational safety columns (added in Phase 1)
    base_run_seconds    = db.Column(db.Integer,    nullable=True)
    min_headway_seconds = db.Column(db.Integer,    nullable=False, default=300)
    capacity            = db.Column(db.Integer,    nullable=False, default=1)
    direction_group     = db.Column(db.String(64), nullable=True)
    is_enabled          = db.Column(db.Boolean,    nullable=False, default=True)

    from_station        = db.relationship("Station", foreign_keys=[from_station_id])
    to_station          = db.relationship("Station", foreign_keys=[to_station_id])

    @property
    def base_time_min(self):
        return float(self._base_time_min or 60.0)

    @base_time_min.setter
    def base_time_min(self, value):
        self._base_time_min = value

    @property
    def distance_km(self):
        return self.base_time_min

    @property
    def dynamic_cost(self):
        traffic_delay = {"clear": 0, "congestion": 15, "delayed": 45}.get(
            self.from_station.status, 0)
        maint_penalty = {"clear": 0, "congestion": 5, "delayed": 10}.get(
            self.to_station.status, 0)
        return self.base_time_min + traffic_delay + maint_penalty

    def to_dict(self):
        return {
            "edge_id":          self.edge_id,
            "from":             self.from_station_id,
            "to":               self.to_station_id,
            "base_time":        self.base_time_min,
            "dynamic_cost":     self.dynamic_cost,
            "distance_km":      self.distance_km,
            "bidirectional":    self.is_bidirectional,
        }


class TrainLocation(db.Model):
    """Legacy real-time train telemetry.  Serves GET /api/trains."""
    __tablename__ = "train_locations"

    train_id        = db.Column("train_id", db.String(20),  primary_key=True)
    train_name      = db.Column(db.String(100), nullable=True)
    current_station = db.Column("current_station", db.String(20),  db.ForeignKey("stations.station_code"), nullable=True)
    delay_minutes   = db.Column(db.Integer,     nullable=False, default=0)
    speed_kmh       = db.Column(db.Float,       nullable=True)
    last_updated    = db.Column(db.DateTime,    nullable=False, default=datetime.utcnow)
    gtfs_trip_id    = db.Column(db.String(40),  nullable=True)

    station         = db.relationship("Station", back_populates="train_locs")

    def to_dict(self):
        return {
            "train_id":        self.train_id,
            "train_name":      self.train_name,
            "current_station": self.current_station,
            "delay_minutes":   self.delay_minutes,
            "speed_kmh":       self.speed_kmh,
            "last_updated":    self.last_updated.isoformat() if self.last_updated else datetime.utcnow().isoformat(),
            "gtfs_trip_id":    self.gtfs_trip_id or f"IR-TRIP-{self.train_id}",
        }


# ══════════════════════════════════════════════════════════════════════════════
# NEW OPERATIONAL MODELS — Phase 1
# ══════════════════════════════════════════════════════════════════════════════

class Train(db.Model):
    """
    Train metadata registry.  train_number is the Indian Railways service
    identifier (e.g. "12301").  Separate from TrainLocation to support the
    one-train-number-many-service-dates pattern in timetable_runs.
    """
    __tablename__ = "trains"

    train_number = db.Column(db.String(16),  primary_key=True)
    train_name   = db.Column(db.String(100), nullable=True)

    runs = db.relationship("TimetableRun", back_populates="train",
                           cascade="all, delete-orphan")

    def to_dict(self):
        return {"train_number": self.train_number, "train_name": self.train_name}


class TimetableRun(db.Model):
    """
    One operating instance of a train on a specific service date.
    The same train_number may run on multiple dates; each has its own run_id.
    """
    __tablename__ = "timetable_runs"

    run_id       = db.Column(db.String(36),  primary_key=True, default=_uuid)
    train_number = db.Column(db.String(16),  db.ForeignKey("trains.train_number"),
                             nullable=False)
    service_date = db.Column(db.Date,        nullable=False)
    run_status   = db.Column(db.String(24),  nullable=False, default="scheduled")
    created_at   = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)

    __table_args__ = (
        db.UniqueConstraint("train_number", "service_date",
                            name="uq_timetable_runs_train_date"),
    )

    train  = db.relationship("Train", back_populates="runs")
    events = db.relationship("TimetableEvent", back_populates="run",
                             cascade="all, delete-orphan",
                             order_by="TimetableEvent.stop_sequence")
    live_states = db.relationship("LiveTrainState", back_populates="run",
                                  cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "run_id":       self.run_id,
            "train_number": self.train_number,
            "service_date": self.service_date.isoformat(),
            "run_status":   self.run_status,
        }


class TimetableEvent(db.Model):
    """Scheduled and actual arrival/departure for each stop in a run."""
    __tablename__ = "timetable_events"

    event_id            = db.Column(db.Integer,  primary_key=True, autoincrement=True)
    run_id              = db.Column(db.String(36), db.ForeignKey("timetable_runs.run_id",
                                   ondelete="CASCADE"), nullable=False)
    station_code        = db.Column(db.String(16), db.ForeignKey("stations.station_code"), nullable=False)
    stop_sequence       = db.Column(db.Integer,  nullable=False)
    scheduled_arrival   = db.Column(db.DateTime(timezone=True), nullable=True)
    scheduled_departure = db.Column(db.DateTime(timezone=True), nullable=True)
    min_dwell_seconds   = db.Column(db.Integer,  nullable=False, default=0)
    actual_arrival      = db.Column(db.DateTime(timezone=True), nullable=True)
    actual_departure    = db.Column(db.DateTime(timezone=True), nullable=True)

    __table_args__ = (
        db.UniqueConstraint("run_id", "stop_sequence",
                            name="uq_timetable_events_run_seq"),
    )

    run     = db.relationship("TimetableRun", back_populates="events")
    station = db.relationship("Station")

    def to_dict(self):
        def _iso(dt):
            return dt.isoformat() if dt else None
        return {
            "event_id":            self.event_id,
            "run_id":              self.run_id,
            "station_code":        self.station_code,
            "stop_sequence":       self.stop_sequence,
            "scheduled_arrival":   _iso(self.scheduled_arrival),
            "scheduled_departure": _iso(self.scheduled_departure),
            "min_dwell_seconds":   self.min_dwell_seconds,
            "actual_arrival":      _iso(self.actual_arrival),
            "actual_departure":    _iso(self.actual_departure),
        }


class LiveTrainState(db.Model):
    """
    Latest observed position and delay for a running train.
    One row per (run_id, observed_at); query for MAX(observed_at) to get
    the current state.
    """
    __tablename__ = "live_train_states"

    live_state_id       = db.Column(db.Integer,  primary_key=True, autoincrement=True)
    run_id              = db.Column(db.String(36), db.ForeignKey("timetable_runs.run_id",
                                   ondelete="CASCADE"), nullable=False)
    observed_at         = db.Column(db.DateTime(timezone=True), nullable=False)
    last_station_code   = db.Column(db.String(16), db.ForeignKey("stations.station_code"), nullable=True)
    next_station_code   = db.Column(db.String(16), db.ForeignKey("stations.station_code"), nullable=True)
    current_segment_id  = db.Column(db.Integer,  db.ForeignKey("station_connections.connection_id"),
                                    nullable=True)
    segment_progress    = db.Column(db.Float,    nullable=True)
    delay_seconds       = db.Column(db.Integer,  nullable=False, default=0)
    speed_kmh           = db.Column(db.Float,    nullable=True)
    source              = db.Column(db.String(64), nullable=True)

    __table_args__ = (
        db.UniqueConstraint("run_id", "observed_at",
                            name="uq_live_states_run_time"),
    )

    run          = db.relationship("TimetableRun", back_populates="live_states")
    last_station = db.relationship("Station", foreign_keys=[last_station_code])
    next_station = db.relationship("Station", foreign_keys=[next_station_code])

    def to_dict(self):
        return {
            "live_state_id":      self.live_state_id,
            "run_id":             self.run_id,
            "observed_at":        self.observed_at.isoformat(),
            "last_station_code":  self.last_station_code,
            "next_station_code":  self.next_station_code,
            "current_segment_id": self.current_segment_id,
            "segment_progress":   self.segment_progress,
            "delay_seconds":      self.delay_seconds,
            "speed_kmh":          self.speed_kmh,
            "source":             self.source,
        }


class DisruptionEvent(db.Model):
    """
    An observed or injected disruption.  Types: train_delay,
    station_congestion, segment_blockage.
    """
    __tablename__ = "disruption_events"

    disruption_id       = db.Column(db.String(36),  primary_key=True, default=_uuid)
    disruption_type     = db.Column(db.String(32),  nullable=False)
    station_code        = db.Column(db.String(16),  db.ForeignKey("stations.station_code"), nullable=True)
    connection_id       = db.Column(db.Integer,     db.ForeignKey("station_connections.connection_id"),
                                    nullable=True)
    reported_at         = db.Column(db.DateTime(timezone=True), nullable=False)
    expected_end_at     = db.Column(db.DateTime(timezone=True), nullable=True)
    observed_delay_seconds = db.Column(db.Integer, nullable=True)
    severity            = db.Column(db.String(16),  nullable=False, default="medium")
    metadata_json       = db.Column(db.JSON,        nullable=False, default=dict)
    is_active           = db.Column(db.Boolean,     nullable=False, default=True)

    station  = db.relationship("Station")

    def to_dict(self):
        return {
            "disruption_id":           self.disruption_id,
            "disruption_type":         self.disruption_type,
            "station_code":            self.station_code,
            "connection_id":           self.connection_id,
            "reported_at":             self.reported_at.isoformat(),
            "expected_end_at":         self.expected_end_at.isoformat() if self.expected_end_at else None,
            "observed_delay_seconds":  self.observed_delay_seconds,
            "severity":                self.severity,
            "metadata":                self.metadata_json,
            "is_active":               self.is_active,
        }


class OperationalSnapshot(db.Model):
    """
    Point-in-time serialised state of the network used to reproduce any
    past rescheduling run.
    """
    __tablename__ = "operational_snapshots"

    snapshot_id       = db.Column(db.String(36), primary_key=True, default=_uuid)
    captured_at       = db.Column(db.DateTime(timezone=True), nullable=False)
    trigger_type      = db.Column(db.String(32), nullable=False)
    trigger_reference = db.Column(db.String(128), nullable=True)
    snapshot_json     = db.Column(db.JSON, nullable=False, default=dict)
    created_at        = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)

    predictions = db.relationship("DelayPrediction", back_populates="snapshot",
                                  cascade="all, delete-orphan")
    rescheduling_runs = db.relationship("ReschedulingRun", back_populates="snapshot")

    def to_dict(self):
        return {
            "snapshot_id":       self.snapshot_id,
            "captured_at":       self.captured_at.isoformat(),
            "trigger_type":      self.trigger_type,
            "trigger_reference": self.trigger_reference,
        }


class DelayPrediction(db.Model):
    """Per-train, per-horizon delay forecast produced by a named predictor."""
    __tablename__ = "delay_predictions"

    prediction_id     = db.Column(db.Integer,   primary_key=True, autoincrement=True)
    snapshot_id       = db.Column(db.String(36), db.ForeignKey("operational_snapshots.snapshot_id",
                                  ondelete="CASCADE"), nullable=False)
    run_id            = db.Column(db.String(36), db.ForeignKey("timetable_runs.run_id",
                                  ondelete="CASCADE"), nullable=False)
    horizon_minutes   = db.Column(db.Integer,   nullable=False)
    p50_delay_seconds = db.Column(db.Integer,   nullable=False)
    p90_delay_seconds = db.Column(db.Integer,   nullable=False)
    model_version     = db.Column(db.String(128), nullable=False)
    created_at        = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)

    __table_args__ = (
        db.UniqueConstraint("snapshot_id", "run_id", "horizon_minutes", "model_version",
                            name="uq_delay_predictions_snap_run_horizon_model"),
    )

    snapshot = db.relationship("OperationalSnapshot", back_populates="predictions")
    run      = db.relationship("TimetableRun")

    def to_dict(self):
        return {
            "prediction_id":     self.prediction_id,
            "snapshot_id":       self.snapshot_id,
            "run_id":            self.run_id,
            "horizon_minutes":   self.horizon_minutes,
            "p50_delay_seconds": self.p50_delay_seconds,
            "p90_delay_seconds": self.p90_delay_seconds,
            "model_version":     self.model_version,
        }


class ReschedulingRun(db.Model):
    """Audit record for one complete execution of the rescheduling engine."""
    __tablename__ = "rescheduling_runs"

    rescheduling_run_id        = db.Column(db.String(36), primary_key=True, default=_uuid)
    snapshot_id                = db.Column(db.String(36), db.ForeignKey("operational_snapshots.snapshot_id"),
                                           nullable=False)
    status                     = db.Column(db.String(24), nullable=False)
    policy_name                = db.Column(db.String(64), nullable=False)
    predictor_name             = db.Column(db.String(64), nullable=False)
    horizon_minutes            = db.Column(db.Integer,    nullable=False)
    commit_window_minutes      = db.Column(db.Integer,    nullable=False)
    objective_before           = db.Column(db.Float,      nullable=True)
    objective_after            = db.Column(db.Float,      nullable=True)
    secondary_delay_before_seconds = db.Column(db.Integer, nullable=True)
    secondary_delay_after_seconds  = db.Column(db.Integer, nullable=True)
    compute_time_ms            = db.Column(db.Integer,    nullable=True)
    configuration              = db.Column(db.JSON,       nullable=False, default=dict)
    created_at                 = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)

    snapshot = db.relationship("OperationalSnapshot", back_populates="rescheduling_runs")
    actions  = db.relationship("ReschedulingAction", back_populates="rescheduling_run",
                               cascade="all, delete-orphan",
                               order_by="ReschedulingAction.action_sequence")
    conflicts = db.relationship("DetectedConflict", back_populates="rescheduling_run",
                                cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "rescheduling_run_id":             self.rescheduling_run_id,
            "snapshot_id":                     self.snapshot_id,
            "status":                          self.status,
            "policy_name":                     self.policy_name,
            "predictor_name":                  self.predictor_name,
            "horizon_minutes":                 self.horizon_minutes,
            "commit_window_minutes":           self.commit_window_minutes,
            "objective_before":                self.objective_before,
            "objective_after":                 self.objective_after,
            "secondary_delay_before_seconds":  self.secondary_delay_before_seconds,
            "secondary_delay_after_seconds":   self.secondary_delay_after_seconds,
            "compute_time_ms":                 self.compute_time_ms,
        }


class ReschedulingAction(db.Model):
    """One recommended action within a rescheduling run."""
    __tablename__ = "rescheduling_actions"

    action_id           = db.Column(db.Integer,   primary_key=True, autoincrement=True)
    rescheduling_run_id = db.Column(db.String(36), db.ForeignKey("rescheduling_runs.rescheduling_run_id",
                                    ondelete="CASCADE"), nullable=False)
    action_sequence     = db.Column(db.Integer,   nullable=False)
    action_type         = db.Column(db.String(32), nullable=False)
    run_id              = db.Column(db.String(36), db.ForeignKey("timetable_runs.run_id"), nullable=True)
    station_code        = db.Column(db.String(16), db.ForeignKey("stations.station_code"), nullable=True)
    connection_id       = db.Column(db.Integer,   db.ForeignKey("station_connections.connection_id"), nullable=True)
    action_payload      = db.Column(db.JSON,       nullable=False, default=dict)
    explanation         = db.Column(db.Text,       nullable=False, default="")

    __table_args__ = (
        db.UniqueConstraint("rescheduling_run_id", "action_sequence",
                            name="uq_rescheduling_actions_run_seq"),
    )

    rescheduling_run = db.relationship("ReschedulingRun", back_populates="actions")

    def to_dict(self):
        return {
            "action_id":       self.action_id,
            "action_sequence": self.action_sequence,
            "action_type":     self.action_type,
            "run_id":          self.run_id,
            "station_code":    self.station_code,
            "connection_id":   self.connection_id,
            "payload":         self.action_payload,
            "explanation":     self.explanation,
        }


class DetectedConflict(db.Model):
    """A headway or resource conflict found during a rescheduling run."""
    __tablename__ = "detected_conflicts"

    conflict_id         = db.Column(db.Integer,   primary_key=True, autoincrement=True)
    rescheduling_run_id = db.Column(db.String(36), db.ForeignKey("rescheduling_runs.rescheduling_run_id",
                                    ondelete="CASCADE"), nullable=False)
    connection_id       = db.Column(db.Integer,   db.ForeignKey("station_connections.connection_id"), nullable=True)
    first_run_id        = db.Column(db.String(36), db.ForeignKey("timetable_runs.run_id"), nullable=False)
    second_run_id       = db.Column(db.String(36), db.ForeignKey("timetable_runs.run_id"), nullable=False)
    conflict_type       = db.Column(db.String(32), nullable=False)
    conflict_start      = db.Column(db.DateTime(timezone=True), nullable=True)
    conflict_end        = db.Column(db.DateTime(timezone=True), nullable=True)
    resolved            = db.Column(db.Boolean,   nullable=False, default=False)
    resolution_action_id = db.Column(db.Integer,  db.ForeignKey("rescheduling_actions.action_id"),
                                     nullable=True)

    rescheduling_run = db.relationship("ReschedulingRun", back_populates="conflicts")

    def to_dict(self):
        return {
            "conflict_id":   self.conflict_id,
            "connection_id": self.connection_id,
            "first_run_id":  self.first_run_id,
            "second_run_id": self.second_run_id,
            "conflict_type": self.conflict_type,
            "resolved":      self.resolved,
        }


class ModelVersion(db.Model):
    """Registry for ML model artifacts (SAGE-Het, DQN, etc.)."""
    __tablename__ = "model_versions"

    model_version = db.Column(db.String(128), primary_key=True)
    model_type    = db.Column(db.String(64),  nullable=False)
    artifact_path = db.Column(db.Text,        nullable=True)
    trained_at    = db.Column(db.DateTime(timezone=True), nullable=True)
    metrics       = db.Column(db.JSON,        nullable=False, default=dict)
    configuration = db.Column(db.JSON,        nullable=False, default=dict)
    is_active     = db.Column(db.Boolean,     nullable=False, default=False)

    def to_dict(self):
        return {
            "model_version": self.model_version,
            "model_type":    self.model_type,
            "artifact_path": self.artifact_path,
            "trained_at":    self.trained_at.isoformat() if self.trained_at else None,
            "metrics":       self.metrics,
            "is_active":     self.is_active,
        }