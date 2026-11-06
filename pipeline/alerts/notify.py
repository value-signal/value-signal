import hmac
from collections.abc import Callable, Mapping
from datetime import date, timedelta
from itertools import groupby

import httpx

from pipeline.alerts.email import EmailError, SendEmail
from pipeline.collect.disclosures_url import viewer_url
from pipeline.collect.titles import is_plan_title, is_progress_title
from pipeline.config import public_site_url, settings
from pipeline.db import Connection

DART_LIST_URL = "https://opendart.fss.or.kr/api/list.json"
DART_NO_DATA = "013"
LOOKBACK_DAYS = 7

STATUS_LABELS = {
    "achieved": "달성",
    "on_track": "진행 중",
    "delayed": "주의",
    "unverifiable": "확인 불가",
}

FetchFilings = Callable[[str, date], list[Mapping]]

SCORE_CHANGE_SQL = """
SELECT s.id, k.metric, s.status, previous.status AS previous_status,
       sub.email, sub.corp_code, c.corp_name
FROM scores s
JOIN kpi_targets k ON k.id = s.kpi_target_id
JOIN companies c ON c.corp_code = k.corp_code
JOIN subscriptions sub ON sub.corp_code = k.corp_code AND sub.status = 'active'
JOIN LATERAL (
    SELECT status FROM scores
    WHERE kpi_target_id = s.kpi_target_id AND id < s.id
    ORDER BY id DESC LIMIT 1
) previous ON true
WHERE s.evaluated_at > sub.confirmed_at AND s.status != previous.status
"""

PENDING_ALERTS_SQL = """
SELECT a.id, a.email, a.corp_code, a.message, a.link, c.corp_name, s.token
FROM alerts a
JOIN companies c ON c.corp_code = a.corp_code
JOIN subscriptions s ON s.email = a.email AND s.corp_code = a.corp_code
WHERE a.sent_at IS NULL
ORDER BY a.email, a.id
"""


def is_cron_authorized(authorization: str | None) -> bool:
    if not settings.cron_secret or not authorization:
        return False
    return hmac.compare_digest(authorization, f"Bearer {settings.cron_secret}")


def fetch_recent_filings(corp_code: str, since: date) -> list[Mapping]:
    """DART 목록 API를 직접 호출한다. 배포 환경에는 OpenDartReader가 없다."""
    response = httpx.get(
        DART_LIST_URL,
        params={
            "crtfc_key": settings.dart_api_key,
            "corp_code": corp_code,
            "bgn_de": since.strftime("%Y%m%d"),
            "pblntf_ty": "I",
            "page_count": 100,
        },
        timeout=15,
    )
    response.raise_for_status()
    body = response.json()
    if body.get("status") == DART_NO_DATA:
        return []
    if body.get("status") != "000":
        raise RuntimeError(f"DART 오류: {body.get('status')}")
    return body.get("list", [])


def _add_alert(conn: Connection, email: str, corp_code: str, kind: str, message: str,
               link: str | None, dedupe_key: str) -> int:
    return conn.execute(
        """
        INSERT INTO alerts (email, corp_code, kind, message, link, dedupe_key)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (email, dedupe_key) DO NOTHING
        """,
        (email, corp_code, kind, message, link, dedupe_key),
    ).rowcount


def detect_new_disclosures(
    conn: Connection, fetch: FetchFilings, today: date | None = None
) -> int:
    """구독 시작 이후 나온 계획·이행현황 공시를 찾아 alerts를 만든다."""
    since = (today or date.today()) - timedelta(days=LOOKBACK_DAYS)
    subscribers = conn.execute(
        """
        SELECT s.email, s.corp_code, s.confirmed_at, c.corp_name
        FROM subscriptions s JOIN companies c USING (corp_code)
        WHERE s.status = 'active'
        ORDER BY s.corp_code
        """
    ).fetchall()

    created = 0
    for corp_code, group in groupby(subscribers, key=lambda row: row["corp_code"]):
        filings = [
            filing
            for filing in fetch(corp_code, since)
            if is_plan_title(filing["report_nm"]) or is_progress_title(filing["report_nm"])
        ]
        for subscriber in group:
            started = subscriber["confirmed_at"].strftime("%Y%m%d")
            for filing in filings:
                if filing["rcept_dt"] < started:
                    continue
                title = " ".join(filing["report_nm"].split())
                created += _add_alert(
                    conn,
                    subscriber["email"],
                    corp_code,
                    "new_disclosure",
                    f"{subscriber['corp_name']} 새 공시: {title}",
                    viewer_url(filing["rcept_no"]),
                    f"disclosure:{filing['rcept_no']}",
                )
    return created


def detect_score_changes(conn: Connection) -> int:
    """구독 시작 이후 채점 상태가 바뀐 약속을 찾아 alerts를 만든다."""
    created = 0
    for row in conn.execute(SCORE_CHANGE_SQL).fetchall():
        before = STATUS_LABELS[row["previous_status"]]
        after = STATUS_LABELS[row["status"]]
        created += _add_alert(
            conn,
            row["email"],
            row["corp_code"],
            "score_change",
            f"{row['corp_name']} {row['metric']}: {before} → {after}",
            f"{public_site_url()}/companies/{row['corp_code']}",
            f"score:{row['id']}",
        )
    return created


def _digest_body(alerts: list[Mapping]) -> str:
    lines = ["오늘의 Value Signal 알림입니다.", ""]
    for alert in alerts:
        lines.append(f"- {alert['message']}")
        if alert["link"]:
            lines.append(f"  {alert['link']}")

    lines += ["", "구독 해지"]
    tokens = {alert["corp_name"]: alert["token"] for alert in alerts}
    for corp_name, token in tokens.items():
        lines.append(f"- {corp_name}: {public_site_url()}/subscription?action=unsubscribe&token={token}")
    return "\n".join(lines) + "\n"


def send_pending_alerts(conn: Connection, send: SendEmail) -> tuple[int, int]:
    """미발송 alerts를 사람별로 묶어 보낸다. 실패한 메일은 다음 실행에서 다시 보낸다."""
    rows = conn.execute(PENDING_ALERTS_SQL).fetchall()
    sent = failed = 0
    for email, group in groupby(rows, key=lambda row: row["email"]):
        if sent >= settings.alert_daily_limit:
            break
        alerts = list(group)
        token = alerts[0]["token"]
        try:
            send(
                email,
                f"[Value Signal] 새 알림 {len(alerts)}건",
                _digest_body(alerts),
                f"{public_site_url()}/subscription?action=unsubscribe&token={token}",
            )
        except EmailError:
            failed += 1
            continue
        conn.execute(
            "UPDATE alerts SET sent_at = now() WHERE id = ANY(%s)",
            ([alert["id"] for alert in alerts],),
        )
        # 이후 실패해도 이미 보낸 메일을 다시 보내지 않도록 바로 확정한다.
        conn.commit()
        sent += 1
    return sent, failed


def remove_stale_pending(conn: Connection) -> int:
    return conn.execute(
        "DELETE FROM subscriptions WHERE status = 'pending'"
        " AND created_at < now() - interval '1 day'"
    ).rowcount


def run_daily_alerts(
    conn: Connection, send: SendEmail, fetch: FetchFilings = fetch_recent_filings
) -> dict[str, int]:
    removed = remove_stale_pending(conn)
    disclosures = detect_new_disclosures(conn, fetch)
    scores = detect_score_changes(conn)
    conn.commit()
    sent, failed = send_pending_alerts(conn, send)
    return {
        "removed_pending": removed,
        "new_disclosures": disclosures,
        "score_changes": scores,
        "sent": sent,
        "failed": failed,
    }
