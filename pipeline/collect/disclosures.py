import re

import OpenDartReader

from pipeline.config import ROOT_DIR, settings
from pipeline.db import Connection

RAW_DIR = ROOT_DIR / "data" / "raw"
PLAN_TITLE = "기업가치제고계획"
PROGRESS_TITLE = "이행현황"
EXCLUDED_TITLES = ("예고", PROGRESS_TITLE)
SEARCH_START = "2024-01-01"
MARKETS = {"Y": "KOSPI", "K": "KOSDAQ"}
VIEWER_URL = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"


def create_dart() -> OpenDartReader:
    return OpenDartReader(settings.dart_api_key)


def is_plan_title(report_name: str) -> bool:
    title = re.sub(r"\s", "", report_name)
    return PLAN_TITLE in title and not any(word in title for word in EXCLUDED_TITLES)


def is_progress_title(report_name: str) -> bool:
    title = re.sub(r"\s", "", report_name)
    return PLAN_TITLE in title and PROGRESS_TITLE in title


def register_company(
    conn: Connection, dart: OpenDartReader, stock_code: str, is_low_pbr: bool
) -> str:
    company = dart.company(stock_code)
    conn.execute(
        """
        INSERT INTO companies (corp_code, stock_code, corp_name, market, is_low_pbr)
        VALUES (%s, %s, %s, %s, %s)
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


def _store_latest(
    conn: Connection,
    dart: OpenDartReader,
    corp_code: str,
    filings,
    disclosure_type: str,
) -> None:
    latest = filings.sort_values("rcept_no").iloc[-1]
    rcept_no = latest["rcept_no"]
    if conn.execute("SELECT 1 FROM disclosures WHERE rcept_no = %s", (rcept_no,)).fetchone():
        return

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    raw_path = RAW_DIR / f"{rcept_no}.xml"
    raw_path.write_text(dart.document(rcept_no, cache=False), encoding="utf-8")

    conn.execute(
        """
        INSERT INTO disclosures
            (rcept_no, corp_code, report_name, disclosure_type, disclosed_at, source_url, raw_path)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (
            rcept_no,
            corp_code,
            re.sub(r"\s+", " ", latest["report_nm"]).strip(),
            disclosure_type,
            latest["rcept_dt"],
            VIEWER_URL.format(rcept_no=rcept_no),
            str(raw_path.relative_to(ROOT_DIR)),
        ),
    )


def collect_plan_disclosures(
    conn: Connection, dart: OpenDartReader, corp_code: str
) -> None:
    """가장 최근 계획 공시와 이행현황 공시의 원문을 받아 disclosures에 저장한다."""
    filings = dart.list(corp_code, start=SEARCH_START, kind="I", final=False)
    if filings.empty:
        return

    for matches, disclosure_type in ((is_plan_title, "plan"), (is_progress_title, "progress")):
        selected = filings[filings["report_nm"].map(matches)]
        if not selected.empty:
            _store_latest(conn, dart, corp_code, selected, disclosure_type)
