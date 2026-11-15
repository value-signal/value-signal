import logging
from collections import Counter, defaultdict
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from api.low_pbr import load_low_pbr_list
from api.qa import QaLimitExceededError, answer_question
from api.subscriptions import (
    SubscriptionLimitError,
    confirm_subscription,
    create_subscription,
    is_valid_email,
    unsubscribe,
)
from pipeline.alerts.email import EmailError, send_email
from pipeline.alerts.notify import is_cron_authorized, run_daily_alerts
from pipeline.collect.news import collect_news_safely
from pipeline.db import Connection, connect
from pipeline.llm import LLMClient, LLMUnavailableError, create_llm_client

KPI_SQL = """
SELECT k.corp_code, k.id, k.category, k.metric, k.measure_type, k.target_min, k.target_max,
       k.unit, k.deadline, k.definition, k.quote, k.review_status, k.review_note, d.source_url,
       s.status, s.achievement_rate, s.elapsed_rate, s.reason, s.evaluated_at,
       s.actual_value, s.actual_unit, s.actual_period
FROM kpi_targets k
JOIN document_chunks c ON c.id = k.chunk_id
JOIN disclosures d ON d.rcept_no = c.rcept_no
LEFT JOIN scores s ON s.id = (
    SELECT id FROM scores WHERE kpi_target_id = k.id ORDER BY evaluated_at DESC, id DESC LIMIT 1
)
WHERE k.review_status != 'rejected'
"""

EXCLUDED_KPI_SQL = """
SELECT id, metric, target_min, target_max, unit, deadline, review_note
FROM kpi_targets WHERE corp_code = %s AND review_status = 'rejected' ORDER BY id
"""

LATEST_PLAN_SQL = """
SELECT report_name, disclosed_at, source_url FROM disclosures
WHERE corp_code = %s AND disclosure_type = 'plan' ORDER BY rcept_no DESC LIMIT 1
"""

KPI_STATUS_COUNT_SQL = """
WITH latest AS (
    SELECT DISTINCT ON (kpi_target_id) kpi_target_id, status FROM scores
    ORDER BY kpi_target_id, evaluated_at DESC, id DESC
)
SELECT k.corp_code, l.status, COUNT(*) AS n
FROM kpi_targets k
LEFT JOIN latest l ON l.kpi_target_id = k.id
WHERE k.review_status != 'rejected'
GROUP BY k.corp_code, l.status
"""

LATEST_PLANS_SQL = """
SELECT DISTINCT ON (corp_code) corp_code, report_name, disclosed_at, source_url
FROM disclosures WHERE disclosure_type = 'plan'
ORDER BY corp_code, rcept_no DESC
"""

NEWS_SQL = """
SELECT n.url, n.title, n.source, n.published_at, n.corp_code, c.corp_name
FROM news n LEFT JOIN companies c ON c.corp_code = n.corp_code
ORDER BY n.published_at DESC LIMIT %s
"""
NEWS_LIMIT = 10

CLAIM_SQL = """
SELECT cl.id, k.metric, cl.claimed_value, cl.unit, cl.period_year, cl.qualifier, cl.quote,
       cl.actual_value, cl.actual_unit, cl.comparison, d.source_url, d.report_name
FROM company_claims cl
JOIN kpi_targets k ON k.id = cl.kpi_target_id
JOIN document_chunks c ON c.id = cl.chunk_id
JOIN disclosures d ON d.rcept_no = c.rcept_no
WHERE k.corp_code = %s
ORDER BY cl.comparison = 'differs' DESC, cl.id
"""

LLM_UNAVAILABLE_MESSAGES = {
    "quota": "AI 사용 한도를 초과했습니다. 잠시 후 다시 시도해 주세요.",
    "timeout": "AI 응답이 지연되고 있습니다. 잠시 후 다시 시도해 주세요.",
    "server": "AI 서비스에 일시적인 문제가 있습니다. 잠시 후 다시 시도해 주세요.",
    "empty_response": "AI가 답변을 만들지 못했습니다. 잠시 후 다시 시도해 주세요.",
}


class Question(BaseModel):
    corp_code: str
    question: str = Field(min_length=2, max_length=300)


class SubscriptionRequest(BaseModel):
    email: str = Field(max_length=254)
    corp_code: str


class TokenRequest(BaseModel):
    token: str = Field(min_length=20, max_length=100)


@lru_cache
def get_qa_llm() -> LLMClient:
    return create_llm_client(max_wait_seconds=5, timeout_seconds=20, max_attempts=1)


logger = logging.getLogger("value_signal")

app = FastAPI(title="Value Signal API")


@app.exception_handler(LLMUnavailableError)
async def llm_unavailable_handler(_: Request, error: LLMUnavailableError) -> JSONResponse:
    headers = {"Retry-After": str(round(error.retry_after))} if error.retry_after else None
    return JSONResponse(
        status_code=503,
        content={"detail": LLM_UNAVAILABLE_MESSAGES[error.reason], "reason": error.reason},
        headers=headers,
    )


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def latest_plan(conn: Connection, corp_code: str) -> dict | None:
    row = conn.execute(LATEST_PLAN_SQL, (corp_code,)).fetchone()
    return dict(row) if row else None


@app.get("/api/companies")
def list_companies() -> list[dict]:
    # 기업 수와 상관없이 쿼리 3번으로 끝낸다. 기업마다 따로 조회하면 원격 DB 왕복이 누적된다.
    with connect() as conn:
        companies = conn.execute("SELECT * FROM companies ORDER BY corp_name").fetchall()
        status_rows = conn.execute(KPI_STATUS_COUNT_SQL).fetchall()
        plans = {
            row.pop("corp_code"): row for row in conn.execute(LATEST_PLANS_SQL).fetchall()
        }

    kpi_counts: Counter[str] = Counter()
    status_counts: defaultdict[str, Counter[str]] = defaultdict(Counter)
    for row in status_rows:
        kpi_counts[row["corp_code"]] += row["n"]
        if row["status"]:
            status_counts[row["corp_code"]][row["status"]] += row["n"]

    return [
        {
            **dict(company),
            "kpi_count": kpi_counts[company["corp_code"]],
            "status_counts": status_counts[company["corp_code"]],
            "latest_plan": plans.get(company["corp_code"]),
        }
        for company in companies
    ]


@app.get("/api/companies/{corp_code}/scorecard")
def get_scorecard(corp_code: str) -> dict:
    with connect() as conn:
        company = conn.execute(
            "SELECT * FROM companies WHERE corp_code = %s", (corp_code,)
        ).fetchone()
        if company is None:
            raise HTTPException(status_code=404, detail="기업을 찾을 수 없습니다")
        kpis = conn.execute(
            f"{KPI_SQL} AND k.corp_code = %s ORDER BY k.category, k.id", (corp_code,)
        ).fetchall()
        excluded = conn.execute(EXCLUDED_KPI_SQL, (corp_code,)).fetchall()
        claims = conn.execute(CLAIM_SQL, (corp_code,)).fetchall()
        plan = latest_plan(conn, corp_code)
    return {
        "company": dict(company),
        "plan": plan,
        "kpis": [dict(row) for row in kpis],
        "excluded": [dict(row) for row in excluded],
        "claims": [dict(row) for row in claims],
    }


@app.get("/api/low-pbr")
def list_low_pbr() -> list[dict]:
    with connect() as conn:
        tracked = {
            row["stock_code"]: row["corp_code"]
            for row in conn.execute("SELECT stock_code, corp_code FROM companies")
        }
    return [
        {**company, "corp_code": tracked.get(company["stock_code"])}
        for company in load_low_pbr_list()
    ]


@app.get("/api/news")
def list_news() -> list[dict]:
    with connect() as conn:
        return conn.execute(NEWS_SQL, (NEWS_LIMIT,)).fetchall()


@app.post("/api/subscriptions", status_code=202)
def subscribe(payload: SubscriptionRequest) -> dict[str, str]:
    email = payload.email.strip().lower()
    if not is_valid_email(email):
        raise HTTPException(status_code=422, detail="이메일 주소를 확인해 주세요")

    with connect() as conn:
        company = conn.execute(
            "SELECT 1 FROM companies WHERE corp_code = %s", (payload.corp_code,)
        ).fetchone()
        if company is None:
            raise HTTPException(status_code=404, detail="기업을 찾을 수 없습니다")
        try:
            create_subscription(conn, send_email, email, payload.corp_code)
        except SubscriptionLimitError as error:
            raise HTTPException(
                status_code=429, detail="요청이 많습니다. 잠시 후 다시 시도해 주세요."
            ) from error
        except EmailError as error:
            logger.warning("확인 메일 발송 실패: %s", error)
            raise HTTPException(
                status_code=503, detail="메일을 보내지 못했습니다. 잠시 후 다시 시도해 주세요."
            ) from error
    # 이미 구독 중인지 알려주지 않도록 항상 같은 응답을 준다.
    return {"detail": "확인 메일을 보냈습니다. 메일의 링크를 누르면 구독이 시작됩니다."}


@app.post("/api/subscriptions/confirm")
def confirm(payload: TokenRequest) -> dict[str, str]:
    with connect() as conn:
        if not confirm_subscription(conn, payload.token):
            raise HTTPException(status_code=404, detail="유효하지 않은 링크입니다")
    return {"detail": "구독이 시작되었습니다."}


@app.post("/api/subscriptions/unsubscribe")
def cancel(payload: TokenRequest) -> dict[str, str]:
    with connect() as conn:
        unsubscribe(conn, payload.token)
    return {"detail": "구독을 해지했습니다."}


@app.get("/api/cron/alerts")
def daily_alerts(authorization: Annotated[str | None, Header()] = None) -> dict[str, int]:
    if not is_cron_authorized(authorization):
        raise HTTPException(status_code=401, detail="인증에 실패했습니다")
    with connect() as conn:
        # 뉴스는 메일과 상관없으므로 먼저 모으고, 실패해도 알림은 보낸다.
        news = collect_news_safely(conn)
        return {**run_daily_alerts(conn, send_email), "news": news}


@app.post("/api/qa")
def ask(payload: Question, llm: Annotated[LLMClient, Depends(get_qa_llm)]) -> dict:
    with connect() as conn:
        company = conn.execute(
            "SELECT 1 FROM companies WHERE corp_code = %s", (payload.corp_code,)
        ).fetchone()
        if company is None:
            raise HTTPException(status_code=404, detail="기업을 찾을 수 없습니다")
        try:
            return answer_question(conn, llm, payload.corp_code, payload.question)
        except QaLimitExceededError as error:
            raise HTTPException(
                status_code=429,
                detail="오늘 사용할 수 있는 질문 횟수를 모두 썼습니다. 내일 다시 시도해 주세요.",
            ) from error
