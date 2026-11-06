import sqlite3


def chunk_disclosure(conn: sqlite3.Connection, rcept_no: str) -> None:
    """공시 원문을 쪼개 페이지·섹션 위치와 함께 document_chunks에 저장한다."""
    raise NotImplementedError
