import pandas as pd

from pipeline.collect.actuals import (
    parse_dividends,
    parse_financials,
    parse_issued_shares,
    parse_treasury,
    to_number,
)

PERIOD = "2025-12-31"


OWNERS_PROFIT = "ifrs-full_ProfitLossAttributableToOwnersOfParent"
OWNERS_COMPREHENSIVE = "ifrs-full_ComprehensiveIncomeAttributableToOwnersOfParent"
OWNERS_EQUITY = "ifrs-full_EquityAttributableToOwnersOfParent"


def statement(rows):
    frame = pd.DataFrame(
        rows, columns=["sj_div", "account_id", "account_nm", "thstrm_amount", "frmtrm_amount"]
    )
    frame["rcept_no"] = "r1"
    return frame


def by_metric(actuals):
    return {actual.metric: actual.value for actual in actuals}


def test_to_number_handles_commas_and_blanks():
    assert to_number("1,234.5") == 1234.5
    assert to_number("-590,019") == -590019
    assert to_number("-") is None


def test_parse_dividends_reads_common_stock_and_separate_payout():
    report = pd.DataFrame(
        [
            ("현금배당금총액(백만원)", "-", "66,971"),
            ("(별도)당기순이익(백만원)", "-", "52,006"),
            ("(연결)현금배당성향(%)", "-", "49.20"),
            ("주당 현금배당금(원)", "보통주", "2,500"),
            ("주당 현금배당금(원)", "우선주", "2,550"),
        ],
        columns=["se", "stock_knd", "thstrm"],
    )
    report["stlm_dt"] = PERIOD
    report["rcept_no"] = "r1"

    actuals, cash_dividend = parse_dividends(report)

    values = by_metric(actuals)
    assert values["dps"] == 2500
    assert values["payout_ratio"] == 49.2
    assert values["payout_ratio_separate"] == 128.78
    assert cash_dividend == 66_971_000_000


def test_parse_treasury_uses_common_stock_total():
    report = pd.DataFrame(
        [
            ("보통주", "기타취득", "99", "99"),
            ("우선주", "총계", "1", "1"),
            ("보통주", "총계", "4,300", "280,000"),
        ],
        columns=["stock_knd", "acqs_mth1", "change_qy_acqs", "change_qy_incnr"],
    )
    report["rcept_no"] = "r1"

    values = by_metric(parse_treasury(report, PERIOD))

    assert values == {"acquired_shares": 4300, "cancelled_shares": 280000}


def test_parse_financials_uses_owners_profit_not_comprehensive_income():
    frame = statement(
        [
            ("BS", "ifrs-full_Equity", "자본총계", "2000", "1800"),
            ("BS", OWNERS_EQUITY, "지배기업의 소유지분", "1100", "900"),
            ("BS", "minority", "비지배주주지분", "900", "900"),
            ("CIS", OWNERS_COMPREHENSIVE, "지배기업 소유주지분", "-999", "0"),
            ("CIS", "ifrs-full_ProfitLoss", "당기순이익(손실)", "300", "100"),
            ("CIS", OWNERS_PROFIT, "지배기업 소유주지분", "100", "50"),
            ("CF", "treasury", "자기주식의 취득", "10", "0"),
        ]
    )

    values = by_metric(parse_financials(frame, PERIOD, cash_dividend=20))

    assert values["roe"] == 10.0
    assert values["total_return_ratio"] == 30.0


def test_parse_financials_falls_back_to_total_for_separate_statements():
    frame = statement(
        [
            ("BS", "ifrs-full_Equity", "자본총계", "1100", "900"),
            ("IS", "ifrs-full_ProfitLoss", "당기순이익", "100", "50"),
        ]
    )

    assert by_metric(parse_financials(frame, PERIOD, None)) == {"roe": 10.0}


def test_parse_financials_skips_return_ratio_on_net_loss():
    frame = statement(
        [
            ("BS", "ifrs-full_Equity", "자본총계", "1100", "900"),
            ("IS", "ifrs-full_ProfitLoss", "당기순이익", "-100", "50"),
        ]
    )

    values = by_metric(parse_financials(frame, PERIOD, cash_dividend=20))

    assert "total_return_ratio" not in values
    assert values["roe"] == -10.0


def test_parse_financials_skips_return_metrics_for_foreign_currency():
    frame = statement(
        [
            ("BS", "ifrs-full_Equity", "자본총계", "1100", "900"),
            ("IS", "ifrs-full_ProfitLoss", "당기순이익", "100", "50"),
        ]
    )
    frame["currency"] = "USD"

    assert by_metric(parse_financials(frame, PERIOD, cash_dividend=20)) == {"roe": 10.0}


def test_parse_issued_shares_reads_common_stock():
    report = pd.DataFrame(
        [("보통주", "27,595,819"), ("합계", "1")], columns=["se", "istc_totqy"]
    )
    report["rcept_no"] = "r1"

    assert parse_issued_shares(report, PERIOD)[0].value == 27_595_819
