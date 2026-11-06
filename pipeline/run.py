import argparse
import csv

from pipeline.collect.actuals import collect_actuals
from pipeline.collect.disclosures import (
    collect_plan_disclosures,
    create_dart,
    register_company,
)
from pipeline.config import ROOT_DIR
from pipeline.db import connect, init_db
from pipeline.extract.kpi import extract_pending, process_disclosure
from pipeline.extract.review import apply_reviews
from pipeline.llm import create_llm_client
from pipeline.scoring.score import score_all

TARGET_COMPANIES_PATH = ROOT_DIR / "data" / "target_companies.csv"


def collect() -> None:
    dart = create_dart()
    with TARGET_COMPANIES_PATH.open(encoding="utf-8", newline="") as file:
        targets = list(csv.DictReader(file))

    with connect() as conn:
        for target in targets:
            corp_code = register_company(
                conn, dart, target["stock_code"], is_low_pbr=target["is_low_pbr"] == "1"
            )
            collect_plan_disclosures(conn, dart, corp_code)
            collect_actuals(conn, dart, corp_code)
            conn.commit()


def extract() -> None:
    llm = create_llm_client()
    with connect() as conn:
        summary = extract_pending(conn, lambda rcept: process_disclosure(conn, llm, rcept))

    print(f"완료 {summary.done}건, 남음 {summary.remaining}건")
    if summary.stopped_by:
        print(f"LLM 사용 불가({summary.stopped_by.reason}). 다시 실행하면 이어서 처리합니다.")


def review() -> None:
    with connect() as conn:
        print(f"검수 반영 {apply_reviews(conn)}건")


def score() -> None:
    with connect() as conn:
        print(f"채점 {score_all(conn)}건")


def alert() -> None:
    raise NotImplementedError("pipeline/alerts 구현 필요")


STEPS = {
    "init-db": init_db,
    "collect": collect,
    "extract": extract,
    "review": review,
    "score": score,
    "alert": alert,
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Value Signal 배치")
    parser.add_argument("step", choices=[*STEPS, "all"])
    args = parser.parse_args()

    for name in STEPS if args.step == "all" else [args.step]:
        print(f"[{name}]")
        STEPS[name]()


if __name__ == "__main__":
    main()
