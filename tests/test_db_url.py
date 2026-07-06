from app import db
from app.config import settings


def test_url_normalized_to_psycopg(monkeypatch):
    monkeypatch.setattr(settings, "database_url", "postgres://u:p@host/db")
    assert db.sqlalchemy_url() == "postgresql+psycopg://u:p@host/db"

    monkeypatch.setattr(settings, "database_url", "postgresql://u:p@host/db")
    assert db.sqlalchemy_url() == "postgresql+psycopg://u:p@host/db"

    monkeypatch.setattr(settings, "database_url", "postgresql+psycopg://u:p@host/db")
    assert db.sqlalchemy_url() == "postgresql+psycopg://u:p@host/db"
