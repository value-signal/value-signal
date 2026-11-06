import pytest

from api.qa import (
    UNANSWERABLE,
    QaLimitExceededError,
    answer_question,
    is_grounded,
)
from pipeline.config import settings
from pipeline.db import connect, init_db
from pipeline.llm import LLMUnavailableError


class FakeLLM:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def complete_json(self, system, user, schema):
        self.calls.append(user)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def grounded_response(**overrides):
    return {
        "answerable": True,
        "answer": "ROE 실적은 12.92%로 목표 15%의 86% 수준입니다.",
        "kpi_ids": [1],
        "chunk_ids": [],
        **overrides,
    }


@pytest.fixture
def conn(tmp_path):
    db_path = tmp_path / "test.sqlite"
    init_db(db_path)
    with connect(db_path) as connection:
        connection.execute(
            "INSERT INTO companies (corp_code, stock_code, corp_name, market)"
            " VALUES ('c1', '000001', '테스트', 'KOSPI')"
        )
        connection.execute(
            "INSERT INTO disclosures (rcept_no, corp_code, report_name, disclosure_type,"
            " disclosed_at, source_url) VALUES ('r1', 'c1', '계획 공시', 'plan', '20241203', 'url')"
        )
        connection.execute(
            "INSERT INTO document_chunks (id, rcept_no, chunk_index, text)"
            " VALUES (7, 'r1', 0, 'ROE 목표 15% 이상')"
        )
        connection.execute(
            "INSERT INTO kpi_targets (id, corp_code, chunk_id, category, metric, measure_type,"
            " target_min, unit, deadline, quote) VALUES"
            " (1, 'c1', 7, 'capital_efficiency', 'ROE', 'level', 15, '%', '2027-12-31',"
            " 'ROE 목표 15% 이상')"
        )
        connection.execute(
            "INSERT INTO scores (kpi_target_id, status, achievement_rate, actual_value,"
            " actual_unit, actual_period) VALUES (1, 'on_track', 0.8613, 12.92, '%', '2025')"
        )
        yield connection


def test_grounded_answer_returns_sources(conn):
    result = answer_question(conn, FakeLLM(grounded_response()), "c1", "ROE는 어떤가요?")

    assert result["answerable"] is True
    assert result["cached"] is False
    assert result["sources"] == [{"label": "ROE", "quote": "ROE 목표 15% 이상", "url": "url"}]


def test_context_contains_scored_numbers(conn):
    llm = FakeLLM(grounded_response())

    answer_question(conn, llm, "c1", "ROE는 어떤가요?")

    assert "2025 실적: 12.92%" in llm.calls[0]
    assert "달성률: 86%" in llm.calls[0]


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"answer": "ROE 실적은 13.5%입니다."}, id="number-not-in-context"),
        pytest.param({"kpi_ids": []}, id="no-citation"),
        pytest.param({"kpi_ids": [999], "chunk_ids": [999]}, id="unknown-citation"),
        pytest.param({"answerable": False}, id="model-declined"),
        pytest.param({"answer": "   "}, id="blank-answer"),
    ],
)
def test_unverified_answer_becomes_unanswerable(conn, overrides):
    result = answer_question(conn, FakeLLM(grounded_response(**overrides)), "c1", "질문입니다")

    assert result["answerable"] is False
    assert result["answer"] == UNANSWERABLE
    assert result["sources"] == []


def test_same_question_uses_cache(conn):
    llm = FakeLLM(grounded_response())

    answer_question(conn, llm, "c1", "ROE는 어떤가요?")
    result = answer_question(conn, llm, "c1", "  ROE는   어떤가요? ")

    assert result["cached"] is True
    assert len(llm.calls) == 1


def test_cache_is_ignored_when_evidence_changes(conn):
    llm = FakeLLM(grounded_response())

    answer_question(conn, llm, "c1", "ROE는 어떤가요?")
    conn.execute(
        "INSERT INTO scores (kpi_target_id, status, actual_value, actual_unit, actual_period)"
        " VALUES (1, 'achieved', 16, '%', '2026')"
    )
    answer_question(conn, llm, "c1", "ROE는 어떤가요?")

    assert len(llm.calls) == 2


def test_daily_limit_blocks_new_questions_but_not_cached_ones(conn, monkeypatch):
    monkeypatch.setattr(settings, "qa_daily_limit", 1)
    llm = FakeLLM(grounded_response())

    answer_question(conn, llm, "c1", "첫 번째 질문")

    with pytest.raises(QaLimitExceededError):
        answer_question(conn, llm, "c1", "두 번째 질문")
    assert answer_question(conn, llm, "c1", "첫 번째 질문")["cached"] is True


def test_llm_failure_is_not_cached(conn):
    with pytest.raises(LLMUnavailableError):
        answer_question(conn, FakeLLM(LLMUnavailableError("quota")), "c1", "질문입니다")

    assert conn.execute("SELECT count(*) FROM qa_answers").fetchone()[0] == 0


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        ("ROE는 12.92%입니다", True),
        ("현금배당 1,000억원입니다", True),
        ("목표 없이 진행 중입니다", True),
        ("ROE는 12.9%입니다", False),
        ("2028년까지입니다", False),
        ("2026.07.01 공시 기준입니다", True),
    ],
)
def test_is_grounded(answer, expected):
    assert is_grounded(answer, "실적 12.92% 2027년 1000억 2026.07.01 공시") is expected
