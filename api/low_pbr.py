import csv
from functools import lru_cache

from pipeline.config import ROOT_DIR

LOW_PBR_PATH = ROOT_DIR / "data" / "low_pbr_list.csv"


@lru_cache
def load_low_pbr_list() -> tuple[dict, ...]:
    """거래소 공표 명단이다. 공표 주기(5월, 11월)마다 파일을 바꾼다."""
    with LOW_PBR_PATH.open(encoding="utf-8", newline="") as file:
        rows = list(csv.DictReader(file))

    return tuple(
        {
            "stock_code": row["stock_code"],
            "corp_name": row["corp_name"],
            "market": row["market"],
            "pbr": float(row["pbr"]),
            "sector": row["sector"],
            "announced_on": row["announced_on"],
            "base_date": row["base_date"],
            "plan_status": row["plan_status"],
            "latest_plan_on": row["latest_plan_on"] or None,
        }
        for row in sorted(rows, key=lambda row: float(row["pbr"]))
    )
