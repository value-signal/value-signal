import re
import sqlite3

import OpenDartReader

from pipeline.config import ROOT_DIR, settings

RAW_DIR = ROOT_DIR / "data" / "raw"
PLAN_TITLE = "기업가치제고계획"
EXCLUDED_TITLES = ("예고", "이행현황")
SEARCH_START = "2024-01-01"
MARKETS = {"Y": "KOSPI", "K": "KOSDAQ"}
VIEWER_URL = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"


def create_dart() -> OpenDartReader:
    return OpenDartReader(settings.dart_api_key)


def is_plan_title(report_name: str) -> bool:
    title = re.sub(r"\s", "", report_name)
    return PLAN_TITLE in title and not any(word in title for word in EXCLUDED_TITLES)


def register_company(
    conn: sqlite3.Connection, dart: OpenDartReader, stock_code: str, is_low_pbr: bool
) -> str:
    company = dart.company(stock_code)
    conn.execute(
        """
        INSERT INTO companies (corp_code, stock_code, corp_name, market, is_low_pbr)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT (corp_code) DO UPDATE SET
            corp_name = excluded.corp_name, is_low_pbr = excluded.is_low_pbr
        """,
        (
            company["corp_code"],
            stock_code,
            company["corp_name"],
            MARKETS[company["corp_cls"]],
            int(is_low_pbr),
        ),
    )
    return company["corp_code"]


def collect_plan_disclosures(
    conn: sqlite3.Connection, dart: OpenDartReader, corp_code: str
) -> None:
    """가장 최근 기업가치 제고 계획 공시의 원문을 받아 disclosures에 저장한다."""
    filings = dart.list(corp_code, start=SEARCH_START, kind="I", final=False)
    if filings.empty:
        return

    plans = filings[filings["report_nm"].map(is_plan_title)]
    if plans.empty:
        return

    latest = plans.sort_values("rcept_no").iloc[-1]
    rcept_no = latest["rcept_no"]
    if conn.execute("SELECT 1 FROM disclosures WHERE rcept_no = ?", (rcept_no,)).fetchone():
        return

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    raw_path = RAW_DIR / f"{rcept_no}.xml"
    raw_path.write_text(dart.document(rcept_no, cache=False), encoding="utf-8")

    conn.execute(
        """
        INSERT INTO disclosures
            (rcept_no, corp_code, report_name, disclosure_type, disclosed_at, source_url, raw_path)
        VALUES (?, ?, ?, 'plan', ?, ?, ?)
        """,
        (
            rcept_no,
            corp_code,
            re.sub(r"\s+", " ", latest["report_nm"]).strip(),
            latest["rcept_dt"],
            VIEWER_URL.format(rcept_no=rcept_no),
            str(raw_path.relative_to(ROOT_DIR)),
        ),
    )
