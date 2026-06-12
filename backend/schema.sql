-- ─────────────────────────────────────────────
-- Rail-Flow AI — MySQL Schema
-- Run once to bootstrap the database.
-- SQLAlchemy will handle subsequent migrations.
-- ─────────────────────────────────────────────

CREATE DATABASE IF NOT EXISTS railflow_db
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE railflow_db;

-- Stations master table
CREATE TABLE IF NOT EXISTS stations (
    id          VARCHAR(10)  NOT NULL PRIMARY KEY,
    name        VARCHAR(120) NOT NULL,
    state       VARCHAR(60)  NOT NULL,
    division    VARCHAR(20),
    zone        VARCHAR(10),
    category    VARCHAR(5),
    layer       VARCHAR(20)  NOT NULL DEFAULT 'corridor',
    priority    TINYINT      NOT NULL DEFAULT 3,
    status      VARCHAR(20)  NOT NULL DEFAULT 'clear',
    CONSTRAINT chk_status CHECK (status IN ('clear','congestion','delayed')),
    CONSTRAINT chk_layer  CHECK (layer  IN ('corridor','hub'))
) ENGINE=InnoDB;

-- Alias mapping (dual-code lookup engine)
CREATE TABLE IF NOT EXISTS station_aliases (
    alias_id    INT          NOT NULL AUTO_INCREMENT PRIMARY KEY,
    station_id  VARCHAR(10)  NOT NULL,
    alias_code  VARCHAR(20)  NOT NULL UNIQUE,
    alias_type  VARCHAR(30)  NOT NULL DEFAULT 'operational',
    CONSTRAINT fk_alias_station
        FOREIGN KEY (station_id) REFERENCES stations(id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE INDEX idx_alias_code ON station_aliases (alias_code);

-- Graph edges
CREATE TABLE IF NOT EXISTS corridor_edges (
    edge_id           INT           NOT NULL AUTO_INCREMENT PRIMARY KEY,
    from_station_id   VARCHAR(10)   NOT NULL,
    to_station_id     VARCHAR(10)   NOT NULL,
    base_time_min     FLOAT         NOT NULL DEFAULT 60.0,
    distance_km       FLOAT,
    is_bidirectional  TINYINT(1)    NOT NULL DEFAULT 1,
    CONSTRAINT fk_edge_from FOREIGN KEY (from_station_id) REFERENCES stations(id),
    CONSTRAINT fk_edge_to   FOREIGN KEY (to_station_id)   REFERENCES stations(id)
) ENGINE=InnoDB;

-- Real-time train telemetry
CREATE TABLE IF NOT EXISTS train_locations (
    train_id         VARCHAR(20)  NOT NULL PRIMARY KEY,
    train_name       VARCHAR(100),
    current_station  VARCHAR(10),
    delay_minutes    INT          NOT NULL DEFAULT 0,
    speed_kmh        FLOAT,
    last_updated     DATETIME     NOT NULL,
    gtfs_trip_id     VARCHAR(40),
    CONSTRAINT fk_train_station
        FOREIGN KEY (current_station) REFERENCES stations(id)
) ENGINE=InnoDB;
