"""Fixture compartido: base de datos temporal por test (Sprint 6)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import db  # noqa: E402


@pytest.fixture()
def bd_temporal(tmp_path, monkeypatch):
    """Cada test mira una taller.db limpia y propia."""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.init_db()
    return db
