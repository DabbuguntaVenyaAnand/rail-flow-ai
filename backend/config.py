"""
config.py — Rail-Flow AI
All runtime settings loaded from environment variables with safe defaults.
"""

import os


class Config:
    # ── Database ──────────────────────────────────────────────────────────
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL",
        "postgresql+psycopg://railflow:railflow@localhost:5432/railflow_db",
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # ── Demo mode ─────────────────────────────────────────────────────────
    # When true: db.create_all() is used for quick startup, deterministic
    # fixtures are loaded, and no random values are generated anywhere.
    DEMO_MODE = os.environ.get("DEMO_MODE", "true").lower() == "true"

    # ── Delay trigger thresholds (minutes) ───────────────────────────────
    DELAY_TRIGGER_MIN = int(os.environ.get("DELAY_TRIGGER_MIN", 5))
    PREDICTED_DELAY_TRIGGER_MIN = int(os.environ.get("PREDICTED_DELAY_TRIGGER_MIN", 8))

    # ── Rolling-horizon parameters ────────────────────────────────────────
    HORIZON_MIN = int(os.environ.get("HORIZON_MIN", 60))
    COMMIT_WINDOW_MIN = int(os.environ.get("COMMIT_WINDOW_MIN", 10))
    ROLLING_REFRESH_SECONDS = int(os.environ.get("ROLLING_REFRESH_SECONDS", 60))

    # ── Impact-zone caps ──────────────────────────────────────────────────
    MAX_IMPACTED_TRAINS = int(os.environ.get("MAX_IMPACTED_TRAINS", 80))
    MAX_IMPACTED_STATIONS = int(os.environ.get("MAX_IMPACTED_STATIONS", 120))

    # ── Headway pruning heuristic ─────────────────────────────────────────
    TRAIN_INTERACTION_HEADWAY_CUTOFF_MIN = int(
        os.environ.get("TRAIN_INTERACTION_HEADWAY_CUTOFF_MIN", 20)
    )

    # ── Predictor and policy selection ───────────────────────────────────
    PREDICTOR_BACKEND = os.environ.get("PREDICTOR_BACKEND", "auto")
    POLICY_BACKEND = os.environ.get("POLICY_BACKEND", "beam_search")

    # ── Beam-search parameters ────────────────────────────────────────────
    BEAM_WIDTH = int(os.environ.get("BEAM_WIDTH", 8))
    MAX_POLICY_EXPANSIONS = int(os.environ.get("MAX_POLICY_EXPANSIONS", 500))
    POLICY_TIME_LIMIT_MS = int(os.environ.get("POLICY_TIME_LIMIT_MS", 1000))
    LOCAL_SEARCH_TIME_LIMIT_MS = int(os.environ.get("LOCAL_SEARCH_TIME_LIMIT_MS", 1000))

    # ── Scenario / uncertainty parameters ────────────────────────────────
    SCENARIO_COUNT = int(os.environ.get("SCENARIO_COUNT", 16))
    RISK_ALPHA = float(os.environ.get("RISK_ALPHA", 0.90))
    RISK_WEIGHT = float(os.environ.get("RISK_WEIGHT", 0.25))

    # ── Feature flags ────────────────────────────────────────────────────
    ENABLE_LOCAL_REROUTE = os.environ.get("ENABLE_LOCAL_REROUTE", "false").lower() == "true"
    ENABLE_CANCELLATION = os.environ.get("ENABLE_CANCELLATION", "false").lower() == "true"
    # Set to "true" in production to activate the rolling-horizon background worker.
    ROLLING_HORIZON_ENABLED = os.environ.get("ROLLING_HORIZON_ENABLED", "true").lower() == "true"


class TestingConfig(Config):
    """Used by pytest: in-memory SQLite so no PostgreSQL needed."""
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    TESTING = True
    DEMO_MODE = True
    WTF_CSRF_ENABLED = False
