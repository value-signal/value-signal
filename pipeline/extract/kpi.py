import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from pydantic import ValidationError

from pipeline.db import Connection
from pipeline.extract.chunking import chunk_disclosure
from pipeline.extract.schema import KpiExtraction, KpiExtractionResult
from pipeline.llm import LLMClient, LLMUnavailableError

SYSTEM_PROMPT = """\
당신은 한국 상장사의 기업가치 제고 계획 공시에서 수치 목표를 추출합니다.
원문에 적힌 내용만 사용하고, 추측하거나 계산하지 않습니다.

추출 대상
- dividend: 배당성향, 주당 배당금, 배당 총액
- treasury_stock: 자기주식 취득, 소각
- shareholder_return: 주주환원율, 총주주환원
- capital_efficiency: ROE, ROIC, ROA

제외 대상
- 매출, 영업이익, PBR, ESG 등 위 분류에 없는 지표
- 과거 실적과 이행 결과. 앞으로 달성할 목표가 아닌 수치
- 고배당기업 여부 표의 수치
- 목표 숫자나 기한이 없는 항목, "ROE > COE"처럼 숫자가 없는 표현
- "검토", "노력"처럼 약속이 아닌 표현

작성 규칙
- 이상은 target_min만, 이하는 target_max만, 범위는 둘 다 채웁니다.
- "최소"는 이상으로 봅니다. 단일값은 target_min과 target_max에 같은 값을 넣습니다.
- 숫자와 단위는 원문 표기 그대로 쓰고 환산하지 않습니다.
- 연도만 있으면 deadline은 그해 12월 31일, 기간이면 마지막 해의 12월 31일로 씁니다.
- 한 시점의 수준을 보는 지표는 level, 기간 합계를 보는 지표는 cumulative로 씁니다.
- 기준값이 원문에 없으면 baseline_value와 baseline_period는 null입니다.
- definition에는 원문의 지표 기준(예: 별도, 연결)을 쓰고, 없으면 null입니다.
- source.chunk_id에는 조각 번호를 쓰고, source.quote에는 목표 숫자가 있는 줄을 원문에서
  글자 그대로 복사합니다.
- 해당하는 목표가 없으면 kpis를 빈 배열로 답합니다.
"""


@dataclass(frozen=True)
class ExtractionSummary:
    done: int
    remaining: int
    stopped_by: LLMUnavailableError | None = None


def extract_kpis(llm: LLMClient, chunks: list[Mapping]) -> list[KpiExtraction]:
    """계획서 조각에서 KPI를 추출한다. 형식이 틀린 항목은 버린다."""
    document = "\n\n".join(f"[조각 {chunk['id']}]\n{chunk['text']}" for chunk in chunks)
    response = llm.complete_json(
        SYSTEM_PROMPT, document, KpiExtractionResult.model_json_schema()
    )

    kpis = []
    for item in response.get("kpis", []):
        try:
            kpis.append(KpiExtraction.model_validate(item))
        except ValidationError:
            continue
    return kpis


def normalize_text(text: str) -> str:
    return "".join(text.split())


def contains_text(text: str, part: str) -> bool:
    return normalize_text(part) in normalize_text(text)


def numbers_in(text: str) -> set[float]:
    return {float(n) for n in re.findall(r"\d+(?:\.\d+)?", text.replace(",", ""))}


def is_quote_verified(kpi: KpiExtraction, chunk_text: str) -> bool:
    """인용문이 원문에 그대로 있는지 확인한다. 없으면 호출부에서 KPI를 폐기한다."""
    return contains_text(chunk_text, kpi.source.quote)


def is_target_in_quote(kpi: KpiExtraction) -> bool:
    """목표 숫자가 인용문에 실제로 있는지 확인한다."""
    targets = {t for t in (kpi.target_min, kpi.target_max) if t is not None}
    return targets <= numbers_in(kpi.source.quote)


def process_disclosure(conn: Connection, llm: LLMClient, rcept_no: str) -> None:
    """공시 하나의 KPI를 추출·검증해 kpi_targets에 저장한다."""
    chunk_disclosure(conn, rcept_no)
    chunks = conn.execute(
        "SELECT id, text FROM document_chunks WHERE rcept_no = %s ORDER BY chunk_index",
        (rcept_no,),
    ).fetchall()
    corp_code = conn.execute(
        "SELECT corp_code FROM disclosures WHERE rcept_no = %s", (rcept_no,)
    ).fetchone()["corp_code"]
    texts = {chunk["id"]: chunk["text"] for chunk in chunks}

    kpis = extract_kpis(llm, chunks)
    verified = [
        kpi
        for kpi in kpis
        if kpi.source.chunk_id in texts
        and is_quote_verified(kpi, texts[kpi.source.chunk_id])
        and is_target_in_quote(kpi)
    ]
    conn.cursor().executemany(
        """
        INSERT INTO kpi_targets
            (corp_code, chunk_id, category, metric, measure_type, target_min, target_max, unit,
             deadline, baseline_value, baseline_period, definition, quote)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        [
            (
                corp_code,
                kpi.source.chunk_id,
                kpi.category,
                kpi.metric,
                kpi.measure_type,
                kpi.target_min,
                kpi.target_max,
                kpi.unit,
                kpi.deadline.isoformat(),
                kpi.baseline_value,
                kpi.baseline_period,
                kpi.definition,
                kpi.source.quote,
            )
            for kpi in verified
        ],
    )
    print(f"{rcept_no}: 저장 {len(verified)}건, 검증 탈락 {len(kpis) - len(verified)}건")


def extract_pending(
    conn: Connection,
    process: Callable[[str], None],
    disclosure_type: str = "plan",
) -> ExtractionSummary:
    """미처리 공시를 차례로 처리한다.

    LLM을 쓸 수 없으면 해당 공시를 되돌리고 멈춘다. 다시 실행하면 그 공시부터 이어서 한다.
    """
    pending = [
        row["rcept_no"]
        for row in conn.execute(
            "SELECT rcept_no FROM disclosures"
            " WHERE extracted_at IS NULL AND disclosure_type = %s ORDER BY disclosed_at",
            (disclosure_type,),
        )
    ]
    for done, rcept_no in enumerate(pending):
        try:
            process(rcept_no)
        except LLMUnavailableError as error:
            conn.rollback()
            return ExtractionSummary(done, len(pending) - done, error)
        conn.execute(
            "UPDATE disclosures SET extracted_at = now() WHERE rcept_no = %s",
            (rcept_no,),
        )
        conn.commit()
    return ExtractionSummary(len(pending), 0)
