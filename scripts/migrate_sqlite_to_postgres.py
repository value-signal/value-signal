"""로컬 SQLite 데이터를 DATABASE_URL의 PostgreSQL로 옮긴다. 대상이 비어 있을 때만 실행한다.

실행: uv run python -m scripts.migrate_sqlite_to_postgres db/value_signal.sqlite
"""
import sqlite3
import sys

from pipeline.db import connect, init_db

TABLES = (
    "companies",
    "disclosures",
    "document_chunks",
    "kpi_targets",
    "actuals",
    "scores",
    "subscriptions",
    "alerts",
    "company_claims",
    "qa_answers",
)
IDENTITY_TABLES = (
    "document_chunks",
    "kpi_targets",
    "actuals",
    "scores",
    "alerts",
    "company_claims",
)


def migrate(sqlite_path: str) -> None:
    source = sqlite3.connect(sqlite_path)
    source.row_factory = sqlite3.Row
    init_db()

    with connect() as conn:
        conn.execute("SET TIME ZONE 'UTC'")
        if conn.execute("SELECT count(*) AS n FROM companies").fetchone()["n"]:
            raise SystemExit("대상 DB에 이미 데이터가 있습니다.")

        for table in TABLES:
            rows = source.execute(f"SELECT * FROM {table}").fetchall()
            if not rows:
                continue
            columns = rows[0].keys()
            placeholders = ", ".join(["%s"] * len(columns))
            conn.cursor().executemany(
                f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})",
                [tuple(row) for row in rows],
            )

        for table in IDENTITY_TABLES:
            conn.execute(
                f"SELECT setval(pg_get_serial_sequence('{table}', 'id'),"
                f" coalesce((SELECT max(id) FROM {table}), 1))"
            )

        for table in TABLES:
            count = conn.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"]
            expected = source.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            if count != expected:
                raise SystemExit(f"{table}: {expected}건 중 {count}건만 옮겨졌습니다.")
            print(f"{table}: {count}건")


if __name__ == "__main__":
    migrate(sys.argv[1])
