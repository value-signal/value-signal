import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from api.main import app, llm_unavailable_handler
from pipeline.config import settings
from pipeline.db import connect
from pipeline.llm import LLMUnavailableError


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "db_path", tmp_path / "test.sqlite")
    with TestClient(app) as test_client:
        yield test_client


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_companies_is_empty_on_new_db(client):
    assert client.get("/api/companies").json() == []


def test_unknown_company_scorecard_returns_404(client):
    assert client.get("/api/companies/none/scorecard").status_code == 404


def test_llm_unavailable_returns_503_with_retry_after():
    response = asyncio.run(llm_unavailable_handler(None, LLMUnavailableError("quota", 30)))

    assert response.status_code == 503
    assert response.headers["retry-after"] == "30"
    assert json.loads(response.body)["reason"] == "quota"


def seed_company(status):
    with connect() as conn:
        conn.execute(
            "INSERT INTO companies (corp_code, stock_code, corp_name, market)"
            " VALUES ('c1', '000001', '테스트', 'KOSPI')"
        )
        conn.execute(
            "INSERT INTO disclosures (rcept_no, corp_code, report_name, disclosure_type,"
            " disclosed_at, source_url) VALUES ('r1', 'c1', '계획', 'plan', '20260701', 'url')"
        )
        conn.execute("INSERT INTO document_chunks (id, rcept_no, chunk_index, text)"
                     " VALUES (1, 'r1', 0, '원문')")
        for kpi_id, review_status in ((1, "pending"), (2, "rejected")):
            conn.execute(
                "INSERT INTO kpi_targets (id, corp_code, chunk_id, category, metric, measure_type,"
                " target_min, unit, deadline, quote, review_status) VALUES"
                " (?, 'c1', 1, 'dividend', '배당성향', 'level', 20, '%', '2030-12-31', '원문', ?)",
                (kpi_id, review_status),
            )
        if status:
            conn.execute(
                "INSERT INTO scores (kpi_target_id, status) VALUES (1, 'on_track'), (1, ?)",
                (status,),
            )


def test_company_list_counts_latest_status_and_skips_rejected_kpi(client):
    seed_company("achieved")

    company = client.get("/api/companies").json()[0]

    assert company["kpi_count"] == 1
    assert company["status_counts"] == {"achieved": 1}
    assert company["latest_plan"]["disclosed_at"] == "20260701"


def test_scorecard_returns_plan_and_unscored_kpi(client):
    seed_company(None)

    scorecard = client.get("/api/companies/c1/scorecard").json()

    assert scorecard["plan"]["source_url"] == "url"
    assert [kpi["id"] for kpi in scorecard["kpis"]] == [1]
    assert scorecard["kpis"][0]["status"] is None
    assert scorecard["kpis"][0]["source_url"] == "url"
    assert [kpi["id"] for kpi in scorecard["excluded"]] == [2]
