import smtplib
from datetime import date, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

import api.main
from api.subscriptions import (
    MAX_REQUESTS_PER_EMAIL_PER_DAY,
    SubscriptionLimitError,
    confirm_subscription,
    create_subscription,
    is_valid_email,
    unsubscribe,
)
from pipeline.alerts import notify
from pipeline.alerts.email import EmailError, build_message, send_email
from pipeline.alerts.notify import (
    detect_new_disclosures,
    detect_score_changes,
    fetch_recent_filings,
    is_cron_authorized,
    run_daily_alerts,
    send_pending_alerts,
)
from pipeline.config import settings
from pipeline.db import connect

EMAIL = "user@example.com"
TODAY = date.today()
PLAN = "기업가치제고계획(자율공시) (2026년)"


class FakeMail:
    def __init__(self, fail=False):
        self.sent = []
        self.fail = fail

    def __call__(self, to, subject, body, unsubscribe_url=None):
        if self.fail:
            raise EmailError("실패")
        self.sent.append({"to": to, "subject": subject, "body": body, "url": unsubscribe_url})


def filing(rcept_no="20261106000001", name=PLAN, day=TODAY):
    return {"rcept_no": rcept_no, "report_nm": name, "rcept_dt": day.strftime("%Y%m%d")}


def no_filings(corp_code, since):
    return []


@pytest.fixture(autouse=True)
def site(monkeypatch):
    monkeypatch.setattr(settings, "site_url", "https://site.test")


@pytest.fixture
def conn(database):
    with connect() as connection:
        connection.execute(
            "INSERT INTO companies (corp_code, stock_code, corp_name, market) VALUES"
            " ('c1', '000001', '테스트', 'KOSPI'), ('c2', '000002', '둘째', 'KOSDAQ')"
        )
        connection.execute(
            "INSERT INTO disclosures (rcept_no, corp_code, report_name, disclosure_type,"
            " disclosed_at, source_url) VALUES ('r1', 'c1', '계획', 'plan', '20250101', 'url')"
        )
        connection.execute(
            "INSERT INTO document_chunks (id, rcept_no, chunk_index, text)"
            " VALUES (100, 'r1', 0, '원문')"
        )
        connection.execute(
            "INSERT INTO kpi_targets (id, corp_code, chunk_id, category, metric, measure_type,"
            " target_min, unit, deadline, quote) VALUES (100, 'c1', 100, 'capital_efficiency',"
            " 'ROE', 'level', 7, '%', '2027-12-31', '원문')"
        )
        yield connection


def subscribed(conn, email=EMAIL, corp_code="c1"):
    """구독을 확인 완료 상태로 만들고 토큰을 돌려준다."""
    create_subscription(conn, FakeMail(), email, corp_code)
    token = conn.execute(
        "SELECT token FROM subscriptions WHERE email = %s AND corp_code = %s", (email, corp_code)
    ).fetchone()["token"]
    confirm_subscription(conn, token)
    return token


def add_score(conn, status):
    conn.execute("INSERT INTO scores (kpi_target_id, status) VALUES (100, %s)", (status,))


def alert_messages(conn):
    rows = conn.execute("SELECT message FROM alerts ORDER BY id").fetchall()
    return [row["message"] for row in rows]


@pytest.mark.parametrize(
    ("email", "expected"),
    [
        ("a@b.co", True),
        ("user.name+tag@example.co.kr", True),
        ("no-at.example.com", False),
        ("a@b", False),
        ("a b@c.com", False),
        ("a@b.com\nBcc: x@y.com", False),
    ],
)
def test_is_valid_email(email, expected):
    assert is_valid_email(email) is expected


def test_unsubscribe_header_stays_readable_and_subject_is_encoded():
    url = "https://site.test/subscription?action=unsubscribe&token=" + "a" * 43

    raw = build_message("a@b.co", "한글 제목", "본문", url).as_bytes()

    assert f"List-Unsubscribe: <{url}>".encode() in raw
    assert "한글 제목".encode() not in raw


def test_send_email_names_missing_settings(monkeypatch):
    monkeypatch.setattr(settings, "smtp_tls", True)
    monkeypatch.setattr(settings, "smtp_host", "smtp.test")
    monkeypatch.setattr(settings, "alert_from", "a@b.co")
    monkeypatch.setattr(settings, "smtp_user", "")
    monkeypatch.setattr(settings, "smtp_password", "")

    with pytest.raises(EmailError, match="SMTP_USER, SMTP_PASSWORD"):
        send_email("a@b.co", "제목", "본문")


def test_send_email_reports_auth_failure_without_server_message(monkeypatch):
    class FailingSmtp:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def starttls(self, context):
            pass

        def ehlo(self):
            pass

        def auth_plain(self, challenge=None):
            return ""

        def auth(self, mechanism, authobject):
            raise smtplib.SMTPAuthenticationError(535, b"secret detail")

    for name, value in (
        ("smtp_tls", True),
        ("smtp_host", "smtp.test"),
        ("smtp_user", "u"),
        ("smtp_password", "p"),
        ("alert_from", "a@b.co"),
    ):
        monkeypatch.setattr(settings, name, value)
    monkeypatch.setattr(smtplib, "SMTP", FailingSmtp)

    with pytest.raises(EmailError) as caught:
        send_email("a@b.co", "제목", "본문")

    assert str(caught.value) == "SMTPAuthenticationError 535"


def test_new_subscription_is_pending_and_sends_confirmation(conn):
    mail = FakeMail()

    create_subscription(conn, mail, EMAIL, "c1")

    row = conn.execute("SELECT status, token FROM subscriptions").fetchone()
    assert row["status"] == "pending"
    assert f"https://site.test/subscription?action=confirm&token={row['token']}" in mail.sent[0]["body"]


def test_existing_subscription_does_not_send_again(conn):
    mail = FakeMail()

    create_subscription(conn, mail, EMAIL, "c1")
    create_subscription(conn, mail, EMAIL, "c1")

    assert len(mail.sent) == 1


def test_requests_per_email_are_limited(conn):
    conn.execute(
        "INSERT INTO companies (corp_code, stock_code, corp_name, market) VALUES"
        " ('c3', '000003', '셋째', 'KOSPI'), ('c4', '000004', '넷째', 'KOSPI')"
    )
    for corp_code in ("c1", "c2", "c3")[:MAX_REQUESTS_PER_EMAIL_PER_DAY]:
        create_subscription(conn, FakeMail(), EMAIL, corp_code)

    with pytest.raises(SubscriptionLimitError):
        create_subscription(conn, FakeMail(), EMAIL, "c4")


def test_total_requests_are_limited(conn, monkeypatch):
    monkeypatch.setattr(settings, "alert_daily_limit", 1)
    create_subscription(conn, FakeMail(), EMAIL, "c1")

    with pytest.raises(SubscriptionLimitError):
        create_subscription(conn, FakeMail(), "other@example.com", "c1")


def test_unconfirmed_subscription_gets_no_alerts(conn):
    create_subscription(conn, FakeMail(), EMAIL, "c1")

    created = detect_new_disclosures(conn, lambda *_: [filing()], TODAY)

    assert created == 0


def test_confirm_activates_and_is_repeatable(conn):
    create_subscription(conn, FakeMail(), EMAIL, "c1")
    row = conn.execute("SELECT token FROM subscriptions").fetchone()

    assert confirm_subscription(conn, row["token"]) is True
    first = conn.execute("SELECT confirmed_at FROM subscriptions").fetchone()["confirmed_at"]
    assert confirm_subscription(conn, row["token"]) is True

    latest = conn.execute("SELECT status, confirmed_at FROM subscriptions").fetchone()
    assert latest == {"status": "active", "confirmed_at": first}


def test_confirm_rejects_unknown_token(conn):
    assert confirm_subscription(conn, "없는토큰") is False


def test_unsubscribe_removes_subscription_and_unsent_alerts(conn):
    token = subscribed(conn)
    detect_new_disclosures(conn, lambda *_: [filing()], TODAY)

    unsubscribe(conn, token)
    unsubscribe(conn, token)

    assert conn.execute("SELECT count(*) AS n FROM subscriptions").fetchone()["n"] == 0
    assert alert_messages(conn) == []


def test_new_plan_disclosure_creates_alert_once(conn):
    subscribed(conn)

    assert detect_new_disclosures(conn, lambda *_: [filing()], TODAY) == 1
    assert detect_new_disclosures(conn, lambda *_: [filing()], TODAY) == 0

    assert alert_messages(conn) == [f"테스트 새 공시: {PLAN}"]


def test_progress_disclosure_is_included_but_unrelated_titles_are_not(conn):
    subscribed(conn)
    filings = [
        filing("1", "기업가치제고계획(자율공시) (2026년 이행현황)"),
        filing("2", "기업가치제고계획예고(안내공시)"),
        filing("3", "주주총회소집결의"),
    ]

    assert detect_new_disclosures(conn, lambda *_: filings, TODAY) == 1


def test_disclosure_before_subscription_is_ignored(conn):
    subscribed(conn)
    old = filing(day=TODAY - timedelta(days=3))

    assert detect_new_disclosures(conn, lambda *_: [old], TODAY) == 0


def test_filings_are_fetched_once_per_company(conn):
    subscribed(conn, "a@example.com")
    subscribed(conn, "b@example.com")
    calls = []

    def fetch(corp_code, since):
        calls.append(corp_code)
        return [filing()]

    assert detect_new_disclosures(conn, fetch, TODAY) == 2
    assert calls == ["c1"]


def test_status_change_after_subscription_creates_alert(conn):
    add_score(conn, "on_track")
    subscribed(conn)
    conn.commit()
    add_score(conn, "delayed")
    conn.commit()

    assert detect_score_changes(conn) == 1
    assert detect_score_changes(conn) == 0
    assert alert_messages(conn) == ["테스트 ROE: 진행 중 → 주의"]


def test_same_status_creates_no_alert(conn):
    add_score(conn, "on_track")
    subscribed(conn)
    conn.commit()
    add_score(conn, "on_track")
    conn.commit()

    assert detect_score_changes(conn) == 0


def test_change_before_subscription_creates_no_alert(conn):
    add_score(conn, "on_track")
    add_score(conn, "delayed")
    conn.commit()
    subscribed(conn)
    conn.commit()

    assert detect_score_changes(conn) == 0


def test_alerts_are_grouped_into_one_mail_per_person(conn):
    subscribed(conn)
    subscribed(conn, corp_code="c2")
    detect_new_disclosures(conn, lambda code, _: [filing(f"{code}1"), filing(f"{code}2")], TODAY)
    mail = FakeMail()

    assert send_pending_alerts(conn, mail) == (1, 0)

    assert len(mail.sent) == 1
    assert mail.sent[0]["subject"] == "[Value Signal] 새 알림 4건"
    assert mail.sent[0]["body"].count("action=unsubscribe") == 2
    assert "action=unsubscribe" in mail.sent[0]["url"]


def test_failed_mail_is_retried_and_sent_mail_is_not_repeated(conn):
    subscribed(conn)
    detect_new_disclosures(conn, lambda *_: [filing()], TODAY)
    mail = FakeMail()

    assert send_pending_alerts(conn, FakeMail(fail=True)) == (0, 1)
    assert send_pending_alerts(conn, mail) == (1, 0)
    assert send_pending_alerts(conn, mail) == (0, 0)

    assert len(mail.sent) == 1


def test_send_stops_at_daily_limit(conn, monkeypatch):
    subscribed(conn, "a@example.com")
    subscribed(conn, "b@example.com")
    detect_new_disclosures(conn, lambda *_: [filing()], TODAY)
    monkeypatch.setattr(settings, "alert_daily_limit", 1)

    assert send_pending_alerts(conn, FakeMail()) == (1, 0)


def test_run_daily_alerts_removes_stale_pending(conn):
    conn.execute(
        "INSERT INTO subscriptions (email, corp_code, token, created_at)"
        " VALUES (%s, 'c1', 't', now() - interval '2 days')",
        (EMAIL,),
    )

    result = run_daily_alerts(conn, FakeMail(), no_filings)

    assert result["removed_pending"] == 1


@pytest.mark.parametrize(
    ("secret", "header", "expected"),
    [
        ("s3cret", "Bearer s3cret", True),
        ("s3cret", "Bearer wrong", False),
        ("s3cret", None, False),
        ("", "Bearer ", False),
    ],
)
def test_is_cron_authorized(monkeypatch, secret, header, expected):
    monkeypatch.setattr(settings, "cron_secret", secret)

    assert is_cron_authorized(header) is expected


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self.body


def test_fetch_recent_filings_reads_list(monkeypatch):
    seen = {}

    def fake_get(url, params, timeout):
        seen.update(params)
        return FakeResponse({"status": "000", "list": [filing()]})

    monkeypatch.setattr(httpx, "get", fake_get)

    assert len(fetch_recent_filings("c1", date(2026, 11, 1))) == 1
    assert seen["bgn_de"] == "20261101"


def test_fetch_recent_filings_treats_no_data_as_empty(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *_, **__: FakeResponse({"status": "013"}))

    assert fetch_recent_filings("c1", TODAY) == []


def test_fetch_recent_filings_raises_on_dart_error(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *_, **__: FakeResponse({"status": "020"}))

    with pytest.raises(RuntimeError):
        fetch_recent_filings("c1", TODAY)


@pytest.fixture
def client(conn, monkeypatch):
    conn.commit()
    mail = FakeMail()
    monkeypatch.setattr(api.main, "send_email", mail)
    with TestClient(api.main.app) as test_client:
        test_client.mail = mail
        yield test_client


def post_subscription(client, email=EMAIL, corp_code="c1"):
    return client.post("/api/subscriptions", json={"email": email, "corp_code": corp_code})


def test_api_subscribe_confirm_unsubscribe_flow(client):
    assert post_subscription(client).status_code == 202
    token = client.mail.sent[0]["body"].split("token=")[1].split()[0]

    assert client.post("/api/subscriptions/confirm", json={"token": token}).status_code == 200
    assert client.post("/api/subscriptions/unsubscribe", json={"token": token}).status_code == 200
    assert client.post("/api/subscriptions/unsubscribe", json={"token": token}).status_code == 200


def test_api_gives_same_response_for_existing_subscriber(client):
    first = post_subscription(client)
    second = post_subscription(client, EMAIL.upper())

    assert first.json() == second.json()
    assert len(client.mail.sent) == 1


@pytest.mark.parametrize(
    ("email", "corp_code", "status"),
    [("잘못된주소", "c1", 422), (EMAIL, "없는기업", 404)],
)
def test_api_rejects_bad_subscription(client, email, corp_code, status):
    assert post_subscription(client, email, corp_code).status_code == status
    assert client.mail.sent == []


def test_api_rolls_back_when_confirmation_mail_fails(client, monkeypatch):
    monkeypatch.setattr(api.main, "send_email", FakeMail(fail=True))

    assert post_subscription(client).status_code == 503

    with connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM subscriptions").fetchone()["n"] == 0


def test_api_rejects_unknown_confirm_token(client):
    response = client.post("/api/subscriptions/confirm", json={"token": "x" * 40})

    assert response.status_code == 404


def test_api_cron_requires_secret(client, monkeypatch):
    monkeypatch.setattr(settings, "cron_secret", "s3cret")
    monkeypatch.setattr(api.main, "run_daily_alerts", lambda conn, send: {"sent": 0})

    assert client.get("/api/cron/alerts").status_code == 401
    wrong = {"Authorization": "Bearer wrong"}
    assert client.get("/api/cron/alerts", headers=wrong).status_code == 401
    right = {"Authorization": "Bearer s3cret"}
    assert client.get("/api/cron/alerts", headers=right).json() == {"sent": 0}


def test_notify_module_has_no_dart_package_dependency():
    assert "OpenDartReader" not in notify.__dict__
