from collections import Counter, defaultdict
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from api.low_pbr import load_low_pbr_list
from api.qa import QaLimitExceededError, answer_question
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


@lru_cache
def get_qa_llm() -> LLMClient:
    return create_llm_client(max_wait_seconds=5, timeout_seconds=20, max_attempts=1)


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
    with connect() as conn:
        companies = conn.execute("SELECT * FROM companies ORDER BY corp_name").fetchall()
        kpis = conn.execute(KPI_SQL).fetchall()
        plans = {row["corp_code"]: latest_plan(conn, row["corp_code"]) for row in companies}

    kpis_by_company = defaultdict(list)
    for kpi in kpis:
        kpis_by_company[kpi["corp_code"]].append(kpi)

    return [
        {
            **dict(company),
            "kpi_count": len(kpis_by_company[company["corp_code"]]),
            "status_counts": Counter(
                kpi["status"] for kpi in kpis_by_company[company["corp_code"]] if kpi["status"]
            ),
            "latest_plan": plans[company["corp_code"]],
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
