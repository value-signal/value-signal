import sqlite3

import pytest

from pipeline.db import connect, init_db


def test_init_db_can_run_twice(tmp_path):
    db_path = tmp_path / "test.sqlite"
    init_db(db_path)
    init_db(db_path)

    with connect(db_path) as conn:
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    assert {"companies", "disclosures", "kpi_targets", "actuals", "scores"} <= tables


def test_foreign_keys_are_enforced(tmp_path):
    db_path = tmp_path / "test.sqlite"
    init_db(db_path)

    with pytest.raises(sqlite3.IntegrityError), connect(db_path) as conn:
        conn.execute(
            "INSERT INTO disclosures (rcept_no, corp_code, report_name, disclosure_type,"
            " disclosed_at, source_url) VALUES ('1', 'missing', '계획', 'I', '2026-01-01', 'url')"
        )
