"""언론사 RSS에서 밸류업 관련 기사 제목과 링크를 모은다. 본문은 저장하지 않는다."""

import html
import logging
import re
import xml.etree.ElementTree as ET
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import httpx

from pipeline.db import Connection

# 구글 뉴스 RSS는 비상업적 개인 이용만 허용해서 쓰지 않는다.
FEEDS = {
    "연합뉴스": "https://www.yna.co.kr/rss/economy.xml",
    "한국경제": "https://www.hankyung.com/feed/finance",
    "매일경제": "https://www.mk.co.kr/rss/50200011/",
}
# 제목에 이 말이 있어야 남긴다. 기업명만 맞는 기사(할인 행사 등)는 거른다.
KEYWORDS = (
    "밸류업",
    "기업가치 제고",
    "기업가치제고",
    "저PBR",
    "주주환원",
    "자사주",
    "자기주식",
    "배당",
)
KEEP_DAYS = 30
KST = timezone(timedelta(hours=9))

TAG_RE = re.compile(r"<[^>]+>")
COMPANY_SUFFIX_RE = re.compile(r"\(주\)|㈜")

logger = logging.getLogger("value_signal")

Fetch = Callable[[str], str]


class NewsError(Exception):
    pass


def fetch_feed(url: str) -> str:
    try:
        response = httpx.get(
            url, timeout=10, follow_redirects=True, headers={"User-Agent": "ValueSignal/1.0"}
        )
        response.raise_for_status()
    except httpx.HTTPError as error:
        raise NewsError(f"RSS를 받지 못했습니다 ({url}): {error}") from error
    return response.text


def clean_title(raw: str) -> str:
    return " ".join(html.unescape(TAG_RE.sub("", raw)).split())


def short_name(corp_name: str) -> str:
    return COMPANY_SUFFIX_RE.sub("", corp_name).strip()


def match_company(title: str, companies: list[tuple[str, str]]) -> str | None:
    """제목에 나온 기업 중 이름이 가장 긴 기업을 고른다. 'LG'보다 'LG화학'을 먼저 본다."""
    for name, corp_code in sorted(companies, key=lambda item: len(item[0]), reverse=True):
        if name in title:
            return corp_code
    return None


def parse_date(value: str | None) -> datetime | None:
    try:
        published_at = parsedate_to_datetime(value or "")
    except (TypeError, ValueError):
        return None
    # '+09:00' 표기는 시간대 없이 읽힌다. 국내 언론사이므로 한국 시간으로 본다.
    return published_at if published_at.tzinfo else published_at.replace(tzinfo=KST)


def parse_feed(xml_text: str, source: str, companies: list[tuple[str, str]]) -> list[dict]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as error:
        raise NewsError(f"{source} RSS 형식을 읽지 못했습니다: {error}") from error

    items = []
    for element in root.iterfind("./channel/item"):
        title = clean_title(element.findtext("title") or "")
        url = (element.findtext("link") or "").strip()
        published_at = parse_date(element.findtext("pubDate"))
        if not title or not url or published_at is None:
            continue
        if not any(keyword in title for keyword in KEYWORDS):
            continue
        items.append(
            {
                "url": url,
                "title": title,
                "source": source,
                "published_at": published_at,
                "corp_code": match_company(title, companies),
            }
        )
    return items


def collect_news(conn: Connection, fetch: Fetch = fetch_feed) -> int:
    """새로 저장한 기사 수를 돌려준다. 한 언론사가 실패해도 나머지는 저장한다."""
    companies = [
        (short_name(row["corp_name"]), row["corp_code"])
        for row in conn.execute("SELECT corp_code, corp_name FROM companies").fetchall()
    ]

    saved = 0
    for source, url in FEEDS.items():
        try:
            items = parse_feed(fetch(url), source, companies)
        except NewsError as error:
            logger.warning("%s", error)
            continue
        for news in items:
            cursor = conn.execute(
                """
                INSERT INTO news (url, title, source, published_at, corp_code)
                VALUES (%(url)s, %(title)s, %(source)s, %(published_at)s, %(corp_code)s)
                ON CONFLICT DO NOTHING
                """,
                news,
            )
            saved += cursor.rowcount

    conn.execute(
        "DELETE FROM news WHERE published_at < now() - make_interval(days => %s)", (KEEP_DAYS,)
    )
    conn.commit()
    return saved


def collect_news_safely(conn: Connection, fetch: Fetch = fetch_feed) -> int:
    """뉴스 수집이 실패해도 같은 예약 작업의 메일 알림은 계속 돌게 한다."""
    try:
        return collect_news(conn, fetch)
    except Exception:
        conn.rollback()
        logger.exception("뉴스 수집 실패")
        return 0
