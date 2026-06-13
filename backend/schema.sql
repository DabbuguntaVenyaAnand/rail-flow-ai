-- ─────────────────────────────────────────────
-- Rail-Flow AI — PostgreSQL Schema Baseline
-- ─────────────────────────────────────────────

-- Create database container if executing outside an existing setup
-- CREATE DATABASE rail_digital_twin;

-- Stations master table (Standardized column names)
CREATE TABLE IF NOT EXISTS public.stations (
    station_code  VARCHAR(20)  NOT NULL PRIMARY KEY,
    station_name  VARCHAR(100) NOT NULL,
    state         VARCHAR(60),
    division      VARCHAR(30),
    zone          VARCHAR(30),
    category      VARCHAR(20),
    layer         VARCHAR(20)  NOT NULL DEFAULT 'corridor',
    status        VARCHAR(20)  NOT NULL DEFAULT 'clear',
    CONSTRAINT chk_status CHECK (status IN ('clear', 'congestion', 'delayed'))
);

-- Alias mapping table
CREATE TABLE IF NOT EXISTS public.station_aliases (
    alias_id    SERIAL       NOT NULL PRIMARY KEY,
    station_code VARCHAR(20)  NOT NULL,
    alias_code  VARCHAR(20)  NOT NULL UNIQUE,
    alias_type  VARCHAR(30)  NOT NULL DEFAULT 'operational',
    CONSTRAINT fk_alias_station
        FOREIGN KEY (station_code) REFERENCES public.stations(station_code) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_alias_code ON public.station_aliases (alias_code);

-- Graph edges (Maps to your live station_connections table configuration)
CREATE TABLE IF NOT EXISTS public.station_connections (
    connection_id       SERIAL         NOT NULL PRIMARY KEY,
    source_station      VARCHAR(20)    NOT NULL,
    destination_station VARCHAR(20)    NOT NULL,
    distance_km         NUMERIC(10,2)  NOT NULL DEFAULT 60.0,
    corridor_name       VARCHAR(100),
    CONSTRAINT uq_connection UNIQUE (source_station, destination_station),
    CONSTRAINT fk_source_station      FOREIGN KEY (source_station)      REFERENCES public.stations(station_code),
    CONSTRAINT fk_destination_station FOREIGN KEY (destination_station) REFERENCES public.stations(station_code)
);

-- Trains structural lookup table
CREATE TABLE IF NOT EXISTS public.trains (
    train_number BIGINT       NOT NULL PRIMARY KEY,
    train_name   VARCHAR(200)
);

-- Train route sequencer table
CREATE TABLE IF NOT EXISTS public.train_routes (
    train_number  BIGINT      NOT NULL,
    station_code  VARCHAR(20) NOT NULL,
    stop_sequence INTEGER     NOT NULL,
    CONSTRAINT train_routes_pkey PRIMARY KEY (train_number, stop_sequence),
    CONSTRAINT fk_route_train    FOREIGN KEY (train_number) REFERENCES public.trains(train_number),
    CONSTRAINT fk_route_station  FOREIGN KEY (station_code) REFERENCES public.stations(station_code)
);