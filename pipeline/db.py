import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from pipeline.config import ROOT_DIR, settings

SCHEMA_PATH = ROOT_DIR / "db" / "schema.sql"


@contextmanager
def connect(db_path: Path | None = None) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(db_path or settings.db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def init_db(db_path: Path | None = None) -> None:
    with connect(db_path) as conn:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
