import sqlite3
from collections.abc import Callable
from dataclasses import dataclass

from pipeline.extract.schema import KpiExtraction
from pipeline.llm import LLMClient, LLMUnavailableError


@dataclass(frozen=True)
class ExtractionSummary:
    done: int
    remaining: int
    stopped_by: LLMUnavailableError | None = None


def extract_kpis(llm: LLMClient, chunks: list[sqlite3.Row]) -> list[KpiExtraction]:
    """계획서 조각에서 KPI를 추출한다."""
    raise NotImplementedError


def is_quote_verified(kpi: KpiExtraction, chunk_text: str) -> bool:
    """인용문이 원문에 그대로 있는지 확인한다. 없으면 호출부에서 KPI를 폐기한다."""
    raise NotImplementedError


def process_disclosure(conn: sqlite3.Connection, llm: LLMClient, rcept_no: str) -> None:
    """공시 하나의 KPI를 추출·검증해 kpi_targets에 저장한다."""
    raise NotImplementedError


def extract_pending(
    conn: sqlite3.Connection, process: Callable[[str], None]
) -> ExtractionSummary:
    """미처리 공시를 차례로 처리한다.

    LLM을 쓸 수 없으면 해당 공시를 되돌리고 멈춘다. 다시 실행하면 그 공시부터 이어서 한다.
    """
    pending = [
        row["rcept_no"]
        for row in conn.execute(
            "SELECT rcept_no FROM disclosures WHERE extracted_at IS NULL ORDER BY disclosed_at"
        )
    ]
    for done, rcept_no in enumerate(pending):
        try:
            process(rcept_no)
        except LLMUnavailableError as error:
            conn.rollback()
            return ExtractionSummary(done, len(pending) - done, error)
        conn.execute(
            "UPDATE disclosures SET extracted_at = datetime('now') WHERE rcept_no = ?",
            (rcept_no,),
        )
        conn.commit()
    return ExtractionSummary(len(pending), 0)
