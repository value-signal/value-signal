import re
import secrets

from pipeline.alerts.email import SendEmail
from pipeline.config import public_site_url, settings
from pipeline.db import Connection

EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
MAX_REQUESTS_PER_EMAIL_PER_DAY = 3


class SubscriptionLimitError(Exception):
    pass


def is_valid_email(email: str) -> bool:
    return EMAIL.fullmatch(email) is not None


def subscription_link(action: str, token: str) -> str:
    return f"{public_site_url()}/subscription?action={action}&token={token}"


def _check_limits(conn: Connection, email: str) -> None:
    usage = conn.execute(
        """
        SELECT count(*) AS total, count(*) FILTER (WHERE email = %s) AS mine
        FROM subscriptions WHERE created_at >= now() - interval '1 day'
        """,
        (email,),
    ).fetchone()
    if usage["mine"] >= MAX_REQUESTS_PER_EMAIL_PER_DAY or usage["total"] >= settings.alert_daily_limit:
        raise SubscriptionLimitError


def create_subscription(
    conn: Connection, send: SendEmail, email: str, corp_code: str
) -> None:
    """구독을 대기 상태로 만들고 확인 메일을 보낸다. 이미 있는 구독은 메일을 다시 보내지 않는다."""
    existing = conn.execute(
        "SELECT 1 FROM subscriptions WHERE email = %s AND corp_code = %s", (email, corp_code)
    ).fetchone()
    if existing:
        return

    _check_limits(conn, email)
    company = conn.execute(
        "SELECT corp_name FROM companies WHERE corp_code = %s", (corp_code,)
    ).fetchone()
    token = secrets.token_urlsafe(32)
    conn.execute(
        "INSERT INTO subscriptions (email, corp_code, token) VALUES (%s, %s, %s)",
        (email, corp_code, token),
    )
    send(
        email,
        f"[Value Signal] {company['corp_name']} 알림 구독을 확인해 주세요",
        f"{company['corp_name']}의 기업가치 제고 목표 알림을 신청하셨습니다.\n\n"
        f"아래 링크를 누르면 구독이 시작됩니다.\n{subscription_link('confirm', token)}\n\n"
        "직접 신청하지 않으셨다면 이 메일을 무시해 주세요. 하루 뒤 정보가 삭제됩니다.\n",
    )


def confirm_subscription(conn: Connection, token: str) -> bool:
    row = conn.execute(
        """
        UPDATE subscriptions
        SET status = 'active', confirmed_at = coalesce(confirmed_at, now())
        WHERE token = %s
        RETURNING email
        """,
        (token,),
    ).fetchone()
    return row is not None


def unsubscribe(conn: Connection, token: str) -> None:
    row = conn.execute(
        "DELETE FROM subscriptions WHERE token = %s RETURNING email, corp_code", (token,)
    ).fetchone()
    if row:
        conn.execute(
            "DELETE FROM alerts WHERE email = %s AND corp_code = %s AND sent_at IS NULL",
            (row["email"], row["corp_code"]),
        )
