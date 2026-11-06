import psycopg
import pytest

from pipeline.db import connect, init_db


def test_init_db_can_run_twice(database):
    init_db()

    with connect() as conn:
        rows = conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
        ).fetchall()
    tables = {row["table_name"] for row in rows}
    assert {"companies", "disclosures", "kpi_targets", "actuals", "scores"} <= tables


def test_foreign_keys_are_enforced(database):
    with pytest.raises(psycopg.errors.ForeignKeyViolation), connect() as conn:
        conn.execute(
            "INSERT INTO disclosures (rcept_no, corp_code, report_name, disclosure_type,"
            " disclosed_at, source_url) VALUES ('1', 'missing', '계획', 'I', '2026-01-01', 'url')"
        )


def test_connection_rolls_back_on_error(database):
    with pytest.raises(RuntimeError), connect() as conn:
        conn.execute(
            "INSERT INTO companies (corp_code, stock_code, corp_name, market)"
            " VALUES ('c1', '000001', '테스트', 'KOSPI')"
        )
        raise RuntimeError

    with connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM companies").fetchone()["n"] == 0
