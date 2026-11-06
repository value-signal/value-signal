"""저장된 KPI를 정답과 비교한다. 대상 공시에 없는 정답은 집계하지 않는다.

실행: uv run python -m evals.evaluate
"""
import csv
from pathlib import Path

from pipeline.db import connect

GOLD_PATH = Path(__file__).with_name("gold_kpis.csv")

EXTRACTED_SQL = """
SELECT c.rcept_no, k.category, k.metric, k.target_min, k.target_max, k.unit, k.deadline
FROM kpi_targets k JOIN document_chunks c ON c.id = k.chunk_id
"""


def _number(value: str | float | None) -> float | None:
    return None if value in (None, "") else float(value)


def _key(row) -> tuple:
    return (
        row["rcept_no"],
        row["category"],
        _number(row["target_min"]),
        _number(row["target_max"]),
        row["unit"],
        row["deadline"],
    )


def main() -> None:
    with GOLD_PATH.open(encoding="utf-8", newline="") as file:
        gold_rows = list(csv.DictReader(file))
    with connect() as conn:
        extracted_rows = conn.execute(EXTRACTED_SQL).fetchall()
        rcept_nos = {row["rcept_no"] for row in conn.execute("SELECT rcept_no FROM disclosures")}

    gold = {_key(row): row["metric"] for row in gold_rows if row["rcept_no"] in rcept_nos}
    extracted = {_key(row): row["metric"] for row in extracted_rows}
    matched = gold.keys() & extracted.keys()

    print(f"정답 {len(gold)}건, 추출 {len(extracted)}건, 일치 {len(matched)}건")
    print(f"정밀도 {len(matched) / len(extracted):.0%}" if extracted else "정밀도 없음")
    print(f"재현율 {len(matched) / len(gold):.0%}" if gold else "재현율 없음")
    for key in gold.keys() - matched:
        print("누락:", gold[key], key)
    for key in extracted.keys() - matched:
        print("오답:", extracted[key], key)


if __name__ == "__main__":
    main()
