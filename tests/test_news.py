from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from api.main import app
from pipeline.collect import news as news_module
from pipeline.collect.news import (
    KST,
    NewsError,
    clean_title,
    collect_news,
    collect_news_safely,
    match_company,
    parse_date,
)
from pipeline.db import connect

NOW = datetime.now(UTC)
COMPANIES = [("LG", "lg"), ("LG화학", "chem")]


def rss(*items):
    body = "".join(
        f"<item><title><![CDATA[{title}]]></title><link>{url}</link>"
        f"<pubDate>{(NOW - timedelta(days=days_ago)).strftime('%a, %d %b %Y %H:%M:%S +0900')}"
        "</pubDate></item>"
        for title, url, days_ago in items
    )
    return f"<rss><channel>{body}</channel></rss>"


@pytest.fixture
def companies(database):
    with connect() as conn:
        conn.execute(
            "INSERT INTO companies (corp_code, stock_code, corp_name, market) VALUES"
            " ('lg', '003550', '(주)LG', 'KOSPI'), ('chem', '051910', 'LG화학', 'KOSPI')"
        )


@pytest.fixture
def one_feed(monkeypatch):
    monkeypatch.setattr(news_module, "FEEDS", {"테스트일보": "https://feed"})


def test_clean_title_removes_tags_and_entities():
    assert clean_title("<b>LG화학</b> &quot;밸류업&quot;  공시") == 'LG화학 "밸류업" 공시'


def test_match_company_prefers_longer_name():
    assert match_company("LG화학, 자사주 소각", COMPANIES) == "chem"
    assert match_company("LG, 배당 확대", COMPANIES) == "lg"
    assert match_company("코스피 마감", COMPANIES) is None


def test_parse_date_treats_colon_offset_as_kst():
    assert parse_date("Sun, 15 Nov 2026 23:05:17 +09:00").tzinfo == KST
    assert parse_date("잘못된 날짜") is None


def test_collect_news_keeps_relevant_and_dedupes(companies, one_feed):
    feed = rss(
        ("LG화학 자사주 소각", "https://a.com/1", 0),
        ("LG화학 자사주 소각", "https://b.com/1", 0),  # 같은 제목, 다른 링크
        ("거래소, 밸류업 지수 발표", "https://a.com/2", 0),
        ("LG화학 신제품 출시", "https://a.com/3", 0),  # 기업명만 맞는 기사
        ("LG 배당 확대", "https://a.com/4", 40),  # 보관 기간 지남
    )

    with connect() as conn:
        saved = collect_news(conn, lambda url: feed)
        rows = conn.execute("SELECT title, source, corp_code FROM news ORDER BY title").fetchall()

    assert saved == 3
    assert rows == [
        {"title": "LG화학 자사주 소각", "source": "테스트일보", "corp_code": "chem"},
        {"title": "거래소, 밸류업 지수 발표", "source": "테스트일보", "corp_code": None},
    ]


def test_collect_news_continues_when_one_feed_fails(companies, monkeypatch):
    monkeypatch.setattr(news_module, "FEEDS", {"A": "https://a", "B": "https://b"})

    def fetch(url):
        if url == "https://a":
            raise NewsError("실패")
        return rss(("밸류업 공시 증가", "https://b.com/1", 0))

    with connect() as conn:
        assert collect_news(conn, fetch) == 1


def test_collect_news_safely_returns_zero_on_unexpected_error(companies):
    def fetch(url):
        raise RuntimeError("예상 못 한 오류")

    with connect() as conn:
        assert collect_news_safely(conn, fetch) == 0


def test_news_api_returns_latest_with_company(companies, one_feed):
    feed = rss(
        ("LG화학 자사주 소각", "https://a.com/1", 1),
        ("밸류업 지수 발표", "https://a.com/2", 0),
    )
    with connect() as conn:
        collect_news(conn, lambda url: feed)

    with TestClient(app) as client:
        news = client.get("/api/news").json()

    assert [row["title"] for row in news] == ["밸류업 지수 발표", "LG화학 자사주 소각"]
    assert news[1]["corp_name"] == "LG화학"
    assert news[1]["source"] == "테스트일보"
    assert news[0]["corp_code"] is None
