import sqlite3


def detect_changes(conn: sqlite3.Connection) -> None:
    """새 공시와 이행률 변화를 찾아 구독자별 alerts를 만든다."""
    raise NotImplementedError


def send_pending_alerts(conn: sqlite3.Connection) -> None:
    """미발송 alerts를 이메일로 보내고 sent_at을 기록한다."""
    raise NotImplementedError
