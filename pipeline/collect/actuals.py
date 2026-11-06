import sqlite3
from dataclasses import dataclass

import OpenDartReader
import pandas as pd

YEARS = (2024, 2025)
WON_PER_MILLION = 1_000_000
WON_PER_EOK = 100_000_000


@dataclass(frozen=True)
class Actual:
    metric: str
    period_end: str
    value: float
    unit: str
    rcept_no: str


def to_number(value) -> float | None:
    text = str(value).replace(",", "").strip()
    try:
        return float(text)
    except ValueError:
        return None


def _dividend_value(report: pd.DataFrame, name: str, stock_kind: str | None = None):
    rows = report[report["se"] == name]
    if stock_kind:
        rows = rows[rows["stock_knd"] == stock_kind]
    return to_number(rows.iloc[0]["thstrm"]) if not rows.empty else None


def parse_dividends(report: pd.DataFrame) -> tuple[list[Actual], float | None]:
    """사업보고서 배당 표에서 실적을 뽑고, 현금배당 총액(원)을 함께 돌려준다."""
    period_end = report.iloc[0]["stlm_dt"]
    rcept_no = report.iloc[0]["rcept_no"]
    cash_dividend = _dividend_value(report, "현금배당금총액(백만원)")
    separate_income = _dividend_value(report, "(별도)당기순이익(백만원)")

    values = {
        ("dps", "원"): _dividend_value(report, "주당 현금배당금(원)", "보통주"),
        ("payout_ratio", "%"): _dividend_value(report, "(연결)현금배당성향(%)"),
    }
    if cash_dividend is not None and separate_income and separate_income > 0:
        values[("payout_ratio_separate", "%")] = round(cash_dividend / separate_income * 100, 2)

    actuals = [
        Actual(metric, period_end, value, unit, rcept_no)
        for (metric, unit), value in values.items()
        if value is not None
    ]
    return actuals, None if cash_dividend is None else cash_dividend * WON_PER_MILLION


def parse_treasury(report: pd.DataFrame, period_end: str) -> list[Actual]:
    """자기주식 표의 보통주 총계에서 취득·소각 주식 수를 뽑는다."""
    total = report[(report["stock_knd"] == "보통주") & (report["acqs_mth1"] == "총계")]
    if total.empty:
        return []
    row = total.iloc[0]
    return [
        Actual(metric, period_end, to_number(row[column]) or 0.0, "주", row["rcept_no"])
        for metric, column in (
            ("acquired_shares", "change_qy_acqs"),
            ("cancelled_shares", "change_qy_incnr"),
        )
    ]


OWNERS_PROFIT_ID = "ifrs-full_ProfitLossAttributableToOwnersOfParent"
TOTAL_PROFIT_ID = "ifrs-full_ProfitLoss"
OWNERS_EQUITY_ID = "ifrs-full_EquityAttributableToOwnersOfParent"
TOTAL_EQUITY_ID = "ifrs-full_Equity"


def _account_by_id(
    statement: pd.DataFrame, sections: tuple[str, ...], account_id: str, column: str
) -> float | None:
    """계정명은 회사마다 달라 표준 계정 ID로 찾는다."""
    rows = statement[
        statement["sj_div"].isin(sections) & (statement["account_id"] == account_id)
    ]
    return to_number(rows.iloc[0][column]) if not rows.empty else None


def _first_available(*values: float | None) -> float | None:
    return next((value for value in values if value is not None), None)


def _net_income(statement: pd.DataFrame) -> float | None:
    sections = ("IS", "CIS")
    return _first_available(
        _account_by_id(statement, sections, OWNERS_PROFIT_ID, "thstrm_amount"),
        _account_by_id(statement, sections, TOTAL_PROFIT_ID, "thstrm_amount"),
    )


def _equity(statement: pd.DataFrame, column: str) -> float | None:
    return _first_available(
        _account_by_id(statement, ("BS",), OWNERS_EQUITY_ID, column),
        _account_by_id(statement, ("BS",), TOTAL_EQUITY_ID, column),
    )


def _buyback(statement: pd.DataFrame) -> float | None:
    rows = statement[
        (statement["sj_div"] == "CF")
        & statement["account_nm"].str.contains("자기주식.*취득|자사주.*취득", regex=True)
    ]
    return to_number(rows.iloc[0]["thstrm_amount"]) if not rows.empty else None


def parse_financials(
    statement: pd.DataFrame, period_end: str, cash_dividend: float | None
) -> list[Actual]:
    """재무제표로 ROE와 표준 주주환원율을 계산한다.

    ROE = 지배주주 순이익 / 평균 지배주주 자본
    주주환원율 = (현금배당 총액 + 자기주식 취득액) / 지배주주 순이익
    """
    income = _net_income(statement)
    equity = _equity(statement, "thstrm_amount")
    prior_equity = _equity(statement, "frmtrm_amount")
    buyback = _buyback(statement)
    rcept_no = statement.iloc[0]["rcept_no"]

    actuals = []
    if income is not None and equity and prior_equity:
        roe = income / ((equity + prior_equity) / 2) * 100
        actuals.append(Actual("roe", period_end, round(roe, 2), "%", rcept_no))

    # 달러 재무제표는 원화 배당금과 더할 수 없다.
    is_krw = statement["currency"].iloc[0] == "KRW" if "currency" in statement else True
    if cash_dividend is not None and is_krw:
        total_return = cash_dividend + abs(buyback or 0)
        actuals.append(
            Actual("total_return_amount", period_end, total_return / WON_PER_EOK, "억원", rcept_no)
        )
        if income and income > 0:
            ratio = round(total_return / income * 100, 2)
            actuals.append(Actual("total_return_ratio", period_end, ratio, "%", rcept_no))
    return actuals


def parse_issued_shares(report: pd.DataFrame, period_end: str) -> list[Actual]:
    common = report[report["se"] == "보통주"]
    if common.empty:
        return []
    shares = to_number(common.iloc[0]["istc_totqy"])
    if not shares:
        return []
    return [Actual("issued_shares", period_end, shares, "주", common.iloc[0]["rcept_no"])]


def _load_statement(dart: OpenDartReader, corp_code: str, year: int) -> pd.DataFrame:
    """연결재무제표를 우선하고, 없으면 별도재무제표를 쓴다."""
    statement = dart.finstate_all(corp_code, year, fs_div="CFS")
    if statement is None or statement.empty:
        statement = dart.finstate_all(corp_code, year, fs_div="OFS")
    return statement


def collect_actuals(conn: sqlite3.Connection, dart: OpenDartReader, corp_code: str) -> None:
    """재무·배당·자사주 실적을 출처 공시와 함께 actuals에 저장한다."""
    actuals: list[Actual] = []
    for year in YEARS:
        dividends = dart.report(corp_code, "배당", year)
        if dividends is None or dividends.empty:
            continue
        rows, cash_dividend = parse_dividends(dividends)
        period_end = dividends.iloc[0]["stlm_dt"]
        actuals += rows

        treasury = dart.report(corp_code, "자기주식", year)
        if treasury is not None and not treasury.empty:
            actuals += parse_treasury(treasury, period_end)

        statement = _load_statement(dart, corp_code, year)
        if statement is not None and not statement.empty:
            actuals += parse_financials(statement, period_end, cash_dividend)

        issued = dart.report(corp_code, "주식총수", year)
        if issued is not None and not issued.empty:
            actuals += parse_issued_shares(issued, period_end)

    conn.executemany(
        """
        INSERT INTO actuals (corp_code, metric, period_end, value, unit, rcept_no)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT (corp_code, metric, period_end, rcept_no) DO UPDATE SET value = excluded.value
        """,
        [(corp_code, a.metric, a.period_end, a.value, a.unit, a.rcept_no) for a in actuals],
    )
