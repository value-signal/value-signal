import pytest

from pipeline.scoring.score import actual_metric_of, elapsed_rate, score_kpi

KPI = {
    "metric": "ROE",
    "unit": "%",
    "definition": None,
    "measure_type": "level",
    "target_min": 10.0,
    "target_max": None,
    "baseline_value": None,
    "deadline": "2027-12-31",
    "start_year": 2025,
    "unscorable_reason": None,
}


def actual(metric, year, value, unit="%", actual_id=1):
    return {
        "id": actual_id,
        "metric": metric,
        "period_end": f"{year}-12-31",
        "value": value,
        "unit": unit,
    }


def score(actuals, plan_year=2024, **overrides):
    return score_kpi({**KPI, **overrides}, plan_year, actuals)


@pytest.mark.parametrize(
    ("metric", "unit", "definition", "expected"),
    [
        ("ROE", "%", None, "roe"),
        ("배당성향", "%", "별도", "payout_ratio_separate"),
        ("배당성향", "%", "연결", "payout_ratio"),
        ("주당 배당금", "원", None, "dps"),
        ("주당배당금(DPS)", "원/주", None, "dps"),
        ("주당배당금 증가율", "%", None, "dps_growth"),
        ("주주환원율", "%", None, "total_return_ratio"),
        ("TPR", "%", None, "total_return_ratio"),
        ("누적 주주환원", "억 원", None, "total_return_amount"),
        ("자사주 소각 비율", "%", None, "cancelled_pct"),
        ("자기주식 소각", "주", None, "cancelled_shares"),
        ("자사주 매입", "%", None, "acquired_pct"),
        ("주당 추가 배당금", "원", None, None),
        ("영업이익 대비 배당", "%", None, None),
    ],
)
def test_actual_metric_of(metric, unit, definition, expected):
    kpi = {"metric": metric, "unit": unit, "definition": definition}

    assert actual_metric_of(kpi) == expected


def test_level_target_met_before_deadline_is_achieved():
    result = score([actual("roe", 2025, 12.0)])

    assert result.status == "achieved"
    assert result.actual_value == 12.0
    assert result.actual_period == "2025"


def test_range_target_is_achieved_at_lower_bound():
    assert score([actual("roe", 2025, 35.0)], target_min=35.0, target_max=40.0).status == "achieved"


def test_behind_within_threshold_is_on_track():
    # 기간 경과율 약 33%, 달성률 20%: 뒤처짐이 20%p 미만이다.
    assert score([actual("roe", 2025, 2.0)]).status == "on_track"


def test_behind_over_threshold_is_delayed():
    # 기간 경과율 약 33%, 달성률 10%: 뒤처짐이 20%p 이상이다.
    assert score([actual("roe", 2025, 1.0)]).status == "delayed"


def test_missed_after_deadline_is_delayed():
    assert score([actual("roe", 2025, 9.0)], deadline="2025-12-31").status == "delayed"


def test_negative_actual_is_delayed():
    assert score([actual("roe", 2025, -5.0)]).status == "delayed"


def test_baseline_is_used_for_achievement_rate():
    result = score([actual("roe", 2025, 7.0)], baseline_value=6.0)

    assert result.achievement_rate == pytest.approx(0.25)


def test_latest_period_is_used_for_level_target():
    result = score([actual("roe", 2024, 12.0), actual("roe", 2025, 1.0)])

    assert result.actual_value == 1.0


def test_cumulative_sums_only_periods_within_range():
    result = score(
        [
            actual("cancelled_shares", 2024, 900, "주"),
            actual("cancelled_shares", 2025, 280, "주"),
        ],
        metric="자기주식 소각",
        unit="주",
        measure_type="cumulative",
        target_min=500.0,
    )

    assert result.actual_value == 280
    assert result.status == "on_track"


def test_cancelled_percent_uses_issued_shares():
    result = score(
        [
            actual("cancelled_shares", 2025, 280_000, "주"),
            actual("issued_shares", 2025, 28_000_000, "주"),
        ],
        metric="자사주 소각 비율",
        measure_type="cumulative",
        target_min=2.0,
        deadline="2026-12-31",
    )

    assert result.actual_value == 1.0
    assert result.status == "on_track"


def test_scaled_unit_is_compared_in_shares():
    result = score(
        [actual("cancelled_shares", 2025, 200_000, "주")],
        metric="자기주식 소각",
        unit="만주",
        target_min=20.0,
    )

    assert result.status == "achieved"


def test_dps_growth_is_measured_from_year_before_start():
    result = score(
        [actual("dps", 2024, 4000, "원"), actual("dps", 2025, 5200, "원")],
        metric="주당배당금 증가율",
        target_min=30.0,
    )

    assert result.actual_value == 30.0
    assert result.status == "achieved"


@pytest.mark.parametrize(
    "overrides",
    [
        {"definition": "EBITDA 기준"},
        {"definition": "일회성 비경상 이익 제외"},
        {"metric": "영업이익 대비 배당"},
        {"unscorable_reason": "사람이 제외"},
    ],
)
def test_non_comparable_kpi_is_unverifiable(overrides):
    result = score([actual("roe", 2025, 12.0)], **overrides)

    assert result.status == "unverifiable"
    assert result.achievement_rate is None


def test_missing_actual_for_level_is_unverifiable():
    assert score([actual("dps", 2025, 100, "원")]).status == "unverifiable"


def test_old_value_is_not_used_when_latest_year_is_missing():
    result = score([actual("roe", 2024, 12.0), actual("dps", 2025, 100, "원")])

    assert result.status == "unverifiable"
    assert result.actual_value is None


def test_policy_starting_after_latest_actual_waits():
    assert score([actual("roe", 2025, 12.0)], start_year=2026) is None


def test_no_actuals_waits():
    assert score([]) is None


def test_elapsed_rate_is_clamped():
    from datetime import date

    assert elapsed_rate(date(2026, 1, 1), date(2027, 1, 1), date(2025, 1, 1)) == 0.0
    assert elapsed_rate(date(2025, 1, 1), date(2026, 1, 1), date(2027, 1, 1)) == 1.0
