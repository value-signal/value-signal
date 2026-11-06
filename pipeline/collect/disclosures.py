import sqlite3


def collect_plan_disclosures(conn: sqlite3.Connection, corp_code: str) -> None:
    """기업가치 제고 계획 공시의 목록과 원문을 수집해 disclosures에 저장한다."""
    raise NotImplementedError
