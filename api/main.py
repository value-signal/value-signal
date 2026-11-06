import sqlite3
from collections import Counter, defaultdict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from pipeline.db import connect, init_db
from pipeline.llm import LLMUnavailableError

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
FROM kpi_targets WHERE corp_code = ? AND review_status = 'rejected' ORDER BY id
"""

LATEST_PLAN_SQL = """
SELECT report_name, disclosed_at, source_url FROM disclosures
WHERE corp_code = ? ORDER BY rcept_no DESC LIMIT 1
"""

LLM_UNAVAILABLE_MESSAGES = {
    "quota": "AI 사용 한도를 초과했습니다. 잠시 후 다시 시도해 주세요.",
    "timeout": "AI 응답이 지연되고 있습니다. 잠시 후 다시 시도해 주세요.",
    "server": "AI 서비스에 일시적인 문제가 있습니다. 잠시 후 다시 시도해 주세요.",
    "empty_response": "AI가 답변을 만들지 못했습니다. 잠시 후 다시 시도해 주세요.",
}


class Question(BaseModel):
    corp_code: str
    question: str


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    init_db()
    yield


app = FastAPI(title="Value Signal API", lifespan=lifespan)


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


def latest_plan(conn: sqlite3.Connection, corp_code: str) -> dict | None:
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
            "SELECT * FROM companies WHERE corp_code = ?", (corp_code,)
        ).fetchone()
        if company is None:
            raise HTTPException(status_code=404, detail="기업을 찾을 수 없습니다")
        kpis = conn.execute(
            f"{KPI_SQL} AND k.corp_code = ? ORDER BY k.category, k.id", (corp_code,)
        ).fetchall()
        excluded = conn.execute(EXCLUDED_KPI_SQL, (corp_code,)).fetchall()
        plan = latest_plan(conn, corp_code)
    return {
        "company": dict(company),
        "plan": plan,
        "kpis": [dict(row) for row in kpis],
        "excluded": [dict(row) for row in excluded],
    }


@app.post("/api/qa", status_code=501)
def ask(_: Question) -> dict[str, str]:
    return {"detail": "근거 Q&A는 아직 구현되지 않았습니다"}
