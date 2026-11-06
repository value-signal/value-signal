from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from pipeline.db import connect, init_db
from pipeline.llm import LLMUnavailableError

LATEST_SCORECARD_SQL = """
SELECT k.id, k.category, k.metric, k.target_value, k.unit, k.deadline, k.quote,
       s.status, s.achievement_rate, s.elapsed_rate, s.reason, s.evaluated_at
FROM kpi_targets k
LEFT JOIN scores s ON s.id = (
    SELECT id FROM scores WHERE kpi_target_id = k.id ORDER BY evaluated_at DESC, id DESC LIMIT 1
)
WHERE k.corp_code = ? AND k.review_status = 'approved'
ORDER BY k.category, k.id
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


@app.get("/api/companies")
def list_companies() -> list[dict]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM companies ORDER BY corp_name").fetchall()
    return [dict(row) for row in rows]


@app.get("/api/companies/{corp_code}/scorecard")
def get_scorecard(corp_code: str) -> dict:
    with connect() as conn:
        company = conn.execute(
            "SELECT * FROM companies WHERE corp_code = ?", (corp_code,)
        ).fetchone()
        if company is None:
            raise HTTPException(status_code=404, detail="기업을 찾을 수 없습니다")
        kpis = conn.execute(LATEST_SCORECARD_SQL, (corp_code,)).fetchall()
    return {"company": dict(company), "kpis": [dict(row) for row in kpis]}


@app.post("/api/qa", status_code=501)
def ask(_: Question) -> dict[str, str]:
    return {"detail": "근거 Q&A는 아직 구현되지 않았습니다"}
