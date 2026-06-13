"""
conftest.py — pytest fixtures for Rail-Flow AI backend tests.

Uses SQLite in-memory so no PostgreSQL is needed to run tests.
The DEMO_MODE=true config ensures db.create_all() runs and the 500-station
seed is loaded automatically.
"""

import sys
import os
import pytest

# Make sure the backend directory is importable regardless of where pytest
# is invoked from.
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app import create_app
from models import db as _db
from config import TestingConfig


@pytest.fixture(scope="session")
def app():
    """
    Create one Flask app for the entire test session.
    SQLite :memory: is faster than file-based; shared across all tests.
    """
    flask_app = create_app({"SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
                            "TESTING": True,
                            "DEMO_MODE": True,
                            "WTF_CSRF_ENABLED": False})
    yield flask_app


@pytest.fixture(scope="session")
def client(app):
    return app.test_client()


@pytest.fixture(scope="session")
def _setup_demo_data(app):
    """Load deterministic demo fixtures once for the session."""
    with app.app_context():
        from fixtures.demo_timetable import load_demo_timetable
        from fixtures.demo_disruptions import load_demo_disruptions
        load_demo_timetable()
        load_demo_disruptions()
    return True
