
from collections.abc import Mapping

from pydantic import ValidationError

from pipeline.db import Connection
from pipeline.extract.chunking import chunk_disclosure
from pipeline.extract.kpi import contains_text, numbers_in
from pipeline.extract.schema import ClaimExtraction, ClaimExtractionResult
from pipeline.llm import LLMClient

SYSTEM_PROMPT = """\
당신은 한국 상장사의 기업가치 제고 계획 이행현황 공시에서, 회사가 스스로 밝힌 실적 수치를 추출합니다.
원문에 적힌 내용만 사용하고, 추측하거나 계산하지 않습니다.

추출 대상
- <약속 목록>의 지표에 대해 회사가 이미 달성했다고 밝힌 사업연도 실적 수치

제외 대상
- 앞으로의 목표, 계획, 예정 수치. "목표" 제목 아래의 수치는 실적이 아닙니다.
- 목록에 없는 지표(매출, 영업이익, PBR 등)
- 전년 대비 증감처럼 지표 값 자체가 아닌 수치
- 숫자가 없는 표현, "35% 수준"처럼 목표를 다시 적은 표현

작성 규칙
- kpi_id에는 <약속 목록>의 번호를 씁니다.
- claimed_value와 unit은 원문 표기 그대로 쓰고 환산하지 않습니다.
- period_year에는 실적이 속한 사업연도를 씁니다. 연도가 불분명하면 추출하지 않습니다.
- qualifier에는 "비경상손익 제외"처럼 회사가 그 수치에 붙인 조건을 원문 그대로 씁니다.
  계산식이 적혀 있으면 계산식을 씁니다. 없으면 null입니다.
- source.chunk_id에는 조각 번호를, source.quote에는 수치가 있는 줄을 원문 그대로 복사합니다.
- 해당하는 수치가 없으면 claims를 빈 배열로 답합니다.
"""

KPI_LIST_SQL = """
SELECT k.id, k.metric, k.unit FROM kpi_targets k
JOIN disclosures d ON d.corp_code = k.corp_code
WHERE d.rcept_no = %s AND k.review_status != 'rejected'
ORDER BY k.id
"""


def extract_claims(
    llm: LLMClient, kpis: list[Mapping], chunks: list[Mapping]
) -> list[ClaimExtraction]:
    """이행현황 공시에서 회사 표현을 뽑는다. 형식이 틀린 항목은 버린다."""
    kpi_list = "\n".join(f"[{kpi['id']}] {kpi['metric']} ({kpi['unit']})" for kpi in kpis)
    document = "\n\n".join(f"[조각 {chunk['id']}]\n{chunk['text']}" for chunk in chunks)
    response = llm.complete_json(
        SYSTEM_PROMPT,
        f"<약속 목록>\n{kpi_list}\n</약속 목록>\n\n<공시>\n{document}\n</공시>",
        ClaimExtractionResult.model_json_schema(),
    )

    claims = []
    for item in response.get("claims", []):
        try:
            claims.append(ClaimExtraction.model_validate(item))
        except ValidationError:
            continue
    return claims


def is_claim_verified(claim: ClaimExtraction, chunk_text: str) -> bool:
    """인용문과 수치가 원문에 있는지 확인한다."""
    return contains_text(chunk_text, claim.source.quote) and claim.claimed_value in numbers_in(
        claim.source.quote
    )


def process_claims(conn: Connection, llm: LLMClient, rcept_no: str) -> None:
    """이행현황 공시 하나의 회사 표현을 추출·검증해 company_claims에 저장한다."""
    chunk_disclosure(conn, rcept_no)
    chunks = conn.execute(
        "SELECT id, text FROM document_chunks WHERE rcept_no = %s ORDER BY chunk_index",
        (rcept_no,),
    ).fetchall()
    kpis = conn.execute(KPI_LIST_SQL, (rcept_no,)).fetchall()
    texts = {chunk["id"]: chunk["text"] for chunk in chunks}
    document = "\n".join(texts.values())
    kpi_ids = {kpi["id"] for kpi in kpis}

    claims = extract_claims(llm, kpis, chunks)
    verified = [
        claim
        for claim in claims
        if claim.kpi_id in kpi_ids
        and claim.source.chunk_id in texts
        and is_claim_verified(claim, texts[claim.source.chunk_id])
    ]
    conn.cursor().executemany(
        """
        INSERT INTO company_claims
            (kpi_target_id, chunk_id, claimed_value, unit, period_year, qualifier, quote)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        [
            (
                claim.kpi_id,
                claim.source.chunk_id,
                claim.claimed_value,
                claim.unit,
                claim.period_year,
                # 원문에 없는 조건은 화면에 보여주지 않는다.
                claim.qualifier
                if claim.qualifier and contains_text(document, claim.qualifier)
                else None,
                claim.source.quote,
            )
            for claim in verified
        ],
    )
    print(f"{rcept_no}: 저장 {len(verified)}건, 검증 탈락 {len(claims) - len(verified)}건")
