import pytest

from pipeline.collect.disclosures import is_plan_title, is_progress_title
from pipeline.db import connect, init_db
from pipeline.extract import chunking, review
from pipeline.extract.claims import process_claims
from pipeline.extract.kpi import extract_pending
from pipeline.scoring.score import compare_all_claims, compare_claim

RAW = "<html><body><p>수익성: 25년 ROE 4.3%</p><p>(비경상손익 제외 수치)</p></body></html>"


def make_claim(chunk_id, kpi_id=1, **overrides):
    return {
        "kpi_id": kpi_id,
        "claimed_value": 4.3,
        "unit": "%",
        "period_year": 2025,
        "qualifier": "비경상손익 제외",
        "source": {"chunk_id": chunk_id, "quote": "수익성: 25년 ROE 4.3%"},
        **overrides,
    }


class FakeLLM:
    def __init__(self, build):
        self.build = build

    def complete_json(self, system, user, schema):
        chunk_id = int(user.split("[조각 ")[1].split("]")[0])
        return {"claims": self.build(chunk_id)}


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(chunking, "ROOT_DIR", tmp_path)
    (tmp_path / "progress.xml").write_text(RAW, encoding="utf-8")
    db_path = tmp_path / "test.sqlite"
    init_db(db_path)
    with connect(db_path) as connection:
        connection.execute(
            "INSERT INTO companies (corp_code, stock_code, corp_name, market)"
            " VALUES ('c1', '000001', '테스트', 'KOSPI')"
        )
        connection.execute(
            "INSERT INTO disclosures (rcept_no, corp_code, report_name, disclosure_type,"
            " disclosed_at, source_url) VALUES ('plan1', 'c1', '계획', 'plan', '20241201', 'url')"
        )
        connection.execute(
            "INSERT INTO disclosures (rcept_no, corp_code, report_name, disclosure_type,"
            " disclosed_at, source_url, raw_path)"
            " VALUES ('p1', 'c1', '이행현황', 'progress', '20260301', 'url', 'progress.xml')"
        )
        connection.execute(
            "INSERT INTO document_chunks (id, rcept_no, chunk_index, text)"
            " VALUES (1, 'plan1', 0, 'ROE 7%')"
        )
        connection.execute(
            "INSERT INTO kpi_targets (id, corp_code, chunk_id, category, metric, measure_type,"
            " target_min, unit, deadline, quote) VALUES"
            " (1, 'c1', 1, 'capital_efficiency', 'ROE', 'level', 7, '%', '2027-12-31', 'ROE 7%')"
        )
        connection.execute(
            "INSERT INTO actuals (corp_code, metric, period_end, value, unit, rcept_no)"
            " VALUES ('c1', 'roe', '2025-12-31', 0.32, '%', 'r')"
        )
        yield connection


def saved_values(conn):
    return [row[0] for row in conn.execute("SELECT claimed_value FROM company_claims")]


@pytest.mark.parametrize(
    ("title", "plan", "progress"),
    [
        ("기업가치제고계획(자율공시) (2026년 이행현황)", False, True),
        ("기업가치제고계획(자율공시) (이행현황 및 고배당기업 표시)", False, True),
        ("기업가치제고계획(자율공시)", True, False),
    ],
)
def test_titles_are_split_by_disclosure_type(title, plan, progress):
    assert is_plan_title(title) is plan
    assert is_progress_title(title) is progress


def test_process_claims_saves_verified_claim(conn):
    process_claims(conn, FakeLLM(lambda chunk_id: [make_claim(chunk_id)]), "p1")

    assert saved_values(conn) == [4.3]


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"claimed_value": 5.0}, id="number-not-in-quote"),
        pytest.param({"source": {"chunk_id": 0, "quote": "없는 문장 4.3%"}}, id="fake-quote"),
        pytest.param({"kpi_id": 999}, id="unknown-kpi"),
    ],
)
def test_process_claims_discards_unverified_claim(conn, overrides):
    def build(chunk_id):
        claim = make_claim(chunk_id, **overrides)
        if "source" in overrides:
            claim["source"]["chunk_id"] = chunk_id
        return [claim]

    process_claims(conn, FakeLLM(build), "p1")

    assert saved_values(conn) == []


def test_fake_qualifier_is_dropped_but_claim_is_kept(conn):
    llm = FakeLLM(lambda chunk_id: [make_claim(chunk_id, qualifier="지어낸 조건")])

    process_claims(conn, llm, "p1")

    assert conn.execute("SELECT qualifier FROM company_claims").fetchone()[0] is None
    assert saved_values(conn) == [4.3]


def test_remove_rejected_claims_deletes_reviewed_claim(conn, tmp_path, monkeypatch):
    reviews = tmp_path / "claim_reviews.csv"
    reviews.write_text("stock_code,metric,claimed_value,reason\n000001,ROE,4.3,목표\n", "utf-8")
    monkeypatch.setattr(review, "CLAIM_REVIEWS_PATH", reviews)
    process_claims(conn, FakeLLM(lambda chunk_id: [make_claim(chunk_id)]), "p1")

    assert review.remove_rejected_claims(conn) == 1
    assert saved_values(conn) == []


def test_extract_pending_keeps_plan_and_progress_separate(conn):
    processed = []

    extract_pending(conn, processed.append, disclosure_type="progress")

    assert processed == ["p1"]


def actual(metric, value, unit="%", year=2025):
    return {"id": 1, "metric": metric, "period_end": f"{year}-12-31", "value": value, "unit": unit}


def claim(value, unit="%", year=2025):
    return {"claimed_value": value, "unit": unit, "period_year": year}


ROE_KPI = {"metric": "ROE", "unit": "%", "definition": None}
SHARE_KPI = {"metric": "자기주식 소각", "unit": "주", "definition": None}


def test_compare_reports_difference():
    assert compare_claim(claim(4.3), ROE_KPI, [actual("roe", 0.32)]) == ("differs", 0.32, "%")


def test_compare_treats_rounding_as_match():
    assert compare_claim(claim(20.0), ROE_KPI, [actual("roe", 20.04)])[0] == "match"


def test_compare_scales_units():
    result = compare_claim(
        claim(20, "만주"), SHARE_KPI, [actual("cancelled_shares", 200_000, "주")]
    )

    assert result[0] == "match"


def test_compare_uses_same_year_only():
    assert compare_claim(claim(4.3, year=2024), ROE_KPI, [actual("roe", 0.32)])[0] == "no_standard"


def test_compare_without_standard_metric():
    kpi = {"metric": "영업이익 대비 배당", "unit": "%", "definition": None}

    assert compare_claim(claim(20.4), kpi, [])[0] == "no_standard"


def test_compare_all_claims_stores_result(conn):
    process_claims(conn, FakeLLM(lambda chunk_id: [make_claim(chunk_id)]), "p1")

    assert compare_all_claims(conn) == 1

    row = conn.execute("SELECT comparison, actual_value FROM company_claims").fetchone()
    assert tuple(row) == ("differs", 0.32)
