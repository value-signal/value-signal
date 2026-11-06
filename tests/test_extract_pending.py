import pytest

from pipeline.db import connect, init_db
from pipeline.extract.kpi import extract_pending
from pipeline.llm import LLMUnavailableError


@pytest.fixture
def conn(tmp_path):
    db_path = tmp_path / "test.sqlite"
    init_db(db_path)
    with connect(db_path) as connection:
        connection.execute(
            "INSERT INTO companies (corp_code, stock_code, corp_name, market)"
            " VALUES ('c1', '000001', '테스트', 'KOSPI')"
        )
        for number in (1, 2, 3):
            connection.execute(
                "INSERT INTO disclosures (rcept_no, corp_code, report_name, disclosure_type,"
                " disclosed_at, source_url) VALUES (?, 'c1', '계획', 'I', ?, 'url')",
                (str(number), f"2026-01-0{number}"),
            )
        connection.commit()
        yield connection


def test_stops_on_llm_failure_and_resumes_from_failed_disclosure(conn):
    def fail_on_second(rcept_no):
        conn.execute("UPDATE companies SET corp_name = ?", (f"처리 {rcept_no}",))
        if rcept_no == "2":
            raise LLMUnavailableError("quota")

    summary = extract_pending(conn, fail_on_second)

    assert (summary.done, summary.remaining) == (1, 2)
    assert summary.stopped_by.reason == "quota"
    assert conn.execute("SELECT corp_name FROM companies").fetchone()[0] == "처리 1"

    processed = []
    summary = extract_pending(conn, processed.append)

    assert processed == ["2", "3"]
    assert (summary.done, summary.remaining, summary.stopped_by) == (2, 0, None)
