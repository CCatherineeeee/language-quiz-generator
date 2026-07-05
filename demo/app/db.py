"""Thin psycopg helper. One connection per call is fine for a single-user demo;
Neon's pooler endpoint handles connection pooling on its side."""
from contextlib import contextmanager
from pathlib import Path
import psycopg
from psycopg.rows import dict_row

from .config import DATABASE_URL

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


@contextmanager
def get_conn():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set (check the project-root .env).")
    conn = psycopg.connect(DATABASE_URL, row_factory=dict_row, connect_timeout=15)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """Create tables if they do not exist."""
    sql = SCHEMA_PATH.read_text()
    with get_conn() as conn:
        conn.execute(sql)


def query(sql, params=None):
    with get_conn() as conn:
        return conn.execute(sql, params or ()).fetchall()


def query_one(sql, params=None):
    with get_conn() as conn:
        return conn.execute(sql, params or ()).fetchone()


def execute(sql, params=None):
    """Run a write and return the first row (use RETURNING)."""
    with get_conn() as conn:
        cur = conn.execute(sql, params or ())
        try:
            return cur.fetchone()
        except psycopg.ProgrammingError:
            return None
