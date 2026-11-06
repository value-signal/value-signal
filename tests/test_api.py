import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from api.main import app, llm_unavailable_handler
from pipeline.config import settings
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
