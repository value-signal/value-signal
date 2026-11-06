import sqlite3


def collect_actuals(conn: sqlite3.Connection, corp_code: str) -> None:
    """재무·배당·자사주 실적을 출처 공시와 함께 actuals에 저장한다."""
    raise NotImplementedError
