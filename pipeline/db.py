from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row

from pipeline.config import ROOT_DIR, settings

SCHEMA_PATH = ROOT_DIR / "db" / "schema.sql"

Connection = psycopg.Connection[dict]


@contextmanager
def connect() -> Iterator[Connection]:
    # Neon 풀러를 쓰므로 prepared statement를 끈다.
    with psycopg.connect(
        settings.database_url, row_factory=dict_row, prepare_threshold=None
    ) as conn:
        yield conn


def init_db() -> None:
    with connect() as conn:
        conn.execute(SCHEMA_PATH.read_text(encoding="utf-8"))
