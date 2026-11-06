import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Literal

from pipeline.db import Connection

Status = Literal["achieved", "on_track", "delayed", "unverifiable"]

DELAY_THRESHOLD = 0.2
NON_STANDARD_DEFINITION = re.compile(r"EBITDA|일회성|비경상|조정")
UNIT_SCALES = {"만주": 10_000}
MATCH_TOLERANCE = 0.01

KPI_SQL = """
SELECT k.*, d.disclosed_at
FROM kpi_targets k
JOIN document_chunks c ON c.id = k.chunk_id
JOIN disclosures d ON d.rcept_no = c.rcept_no
WHERE k.review_status != 'rejected'
"""


@dataclass(frozen=True)
class ScoreResult:
    status: Status
    achievement_rate: float | None
    elapsed_rate: float | None
    reason: str | None
    actual_ids: list[int]
    actual_value: float | None = None
    actual_unit: str | None = None
    actual_period: str | None = None


def unverifiable(reason: str) -> ScoreResult:
    return ScoreResult("unverifiable", None, None, reason, [])


def target_of(kpi: Mapping) -> float:
    target = kpi["target_min"] if kpi["target_min"] is not None else kpi["target_max"]
    return target * UNIT_SCALES.get(kpi["unit"], 1)


def actual_metric_of(kpi: Mapping) -> str | None:
    """KPI를 비교할 표준 실적 지표로 바꾼다. 기준을 맞출 수 없으면 None을 반환한다."""
    metric = kpi["metric"]
    unit = kpi["unit"]
    definition = kpi["definition"] or ""

    if "ROE" in metric:
        return "roe"
    if "증가율" in metric and "배당" in metric:
        return "dps_growth"
    if "추가" in metric or "대비" in metric:
        return None
    if "배당성향" in metric:
        return "payout_ratio_separate" if "별도" in definition else "payout_ratio"
    if re.search(r"주당.*배당|DPS", metric) and unit.startswith("원"):
        return "dps"
    if re.search(r"주주환원율|TSR|TPR", metric):
        return "total_return_ratio"
    if "누적 주주환원" in metric and "억" in unit:
        return "total_return_amount"
    if "소각" in metric:
        return "cancelled_pct" if unit == "%" else "cancelled_shares"
    if "매입" in metric and unit == "%":
        return "acquired_pct"
    return None


def elapsed_rate(start: date, deadline: date, evaluated_on: date) -> float:
    if deadline <= start:
        return 1.0
    return min(max((evaluated_on - start).days / (deadline - start).days, 0.0), 1.0)


def _series(actuals: Sequence[Mapping], metric: str) -> list[Mapping]:
    return sorted((a for a in actuals if a["metric"] == metric), key=lambda a: a["period_end"])


def _resolve_actual(
    metric: str,
    actuals: Sequence[Mapping],
    start_year: int,
    deadline_year: int,
    cumulative: bool,
    latest_period: str,
) -> tuple[float, str, list[Mapping]] | None:
    """(비교값, 단위, 사용한 실적)을 계산한다. 값을 만들 수 없으면 None을 반환한다.

    최신 실적이 없을 때 지난해 값을 대신 쓰지 않는다.
    """
    if metric == "dps_growth":
        dps = _series(actuals, "dps")
        base = [a for a in dps if int(a["period_end"][:4]) == start_year - 1]
        current = [a for a in dps if a["period_end"] == latest_period]
        if not base or not current or base[0]["value"] <= 0 or current[0] is base[0]:
            return None
        growth = (current[0]["value"] / base[0]["value"] - 1) * 100
        return round(growth, 2), "%", [base[0], current[0]]

    source = {"cancelled_pct": "cancelled_shares", "acquired_pct": "acquired_shares"}.get(
        metric, metric
    )
    rows = _series(actuals, source)
    if cumulative:
        used = [a for a in rows if start_year <= int(a["period_end"][:4]) <= deadline_year]
    else:
        used = [a for a in rows if a["period_end"] == latest_period]
    if not used:
        return None
    value = sum(a["value"] for a in used)

    if metric in ("cancelled_pct", "acquired_pct"):
        issued = _series(actuals, "issued_shares")
        if not issued:
            return None
        return round(value / issued[-1]["value"] * 100, 2), "%", used
    return value, used[-1]["unit"], used


def score_kpi(kpi: Mapping, plan_year: int, actuals: Sequence[Mapping]) -> ScoreResult | None:
    """달성률과 기간 경과율로 상태를 정한다. 아직 비교할 실적이 없으면 None을 반환한다.

    달성률 = (실적 - 기준값) / (목표 - 기준값). 기준값이 없으면 0으로 본다.
    기간 경과율 = (실적 기준일 - 시작일) / (기한 - 시작일)
    달성률이 기간 경과율보다 DELAY_THRESHOLD 이상 뒤처지거나 기한까지 미달이면 delayed다.

    이 패키지에서는 LLM을 호출하지 않는다.
    """
    if kpi["unscorable_reason"]:
        return unverifiable(kpi["unscorable_reason"])
    definition = kpi["definition"] or ""
    if NON_STANDARD_DEFINITION.search(definition):
        return unverifiable(f"회사 기준({definition})이 공시 표준 지표와 다릅니다")

    metric = actual_metric_of(kpi)
    if metric is None:
        return unverifiable("DART 표준 데이터로 계산할 수 없습니다")

    start_year = kpi["start_year"] or plan_year
    deadline = date.fromisoformat(kpi["deadline"])
    periods = [a["period_end"] for a in actuals]
    if not periods:
        return None
    latest = date.fromisoformat(max(periods))
    if kpi["start_year"] and latest.year < kpi["start_year"]:
        return None

    cumulative = kpi["measure_type"] == "cumulative"
    resolved = _resolve_actual(
        metric, actuals, start_year, deadline.year, cumulative, latest.isoformat()
    )
    if resolved is None:
        if cumulative:
            return None
        return unverifiable(f"{latest.year} 사업연도 실적으로 계산할 수 없습니다 (순손실, 무배당, 외화 재무제표 등)")
    value, unit, used = resolved

    target = target_of(kpi)
    baseline = 0.0 if cumulative else kpi["baseline_value"] or 0.0
    achievement = (value - baseline) / (target - baseline) if target != baseline else None
    elapsed = elapsed_rate(date(start_year, 1, 1), deadline, latest)

    met = value <= target if kpi["target_min"] is None else value >= target
    if met:
        status: Status = "achieved"
    elif latest >= deadline or achievement is not None and achievement < elapsed - DELAY_THRESHOLD:
        status = "delayed"
    else:
        status = "on_track"

    return ScoreResult(
        status=status,
        achievement_rate=achievement,
        elapsed_rate=elapsed,
        reason=None,
        actual_ids=[a["id"] for a in used],
        actual_value=value,
        actual_unit=unit,
        actual_period=str(latest.year),
    )


def _is_same_as_latest(conn: Connection, kpi_id: int, result: ScoreResult) -> bool:
    latest = conn.execute(
        "SELECT status, actual_value, reason FROM scores WHERE kpi_target_id = %s"
        " ORDER BY evaluated_at DESC, id DESC LIMIT 1",
        (kpi_id,),
    ).fetchone()
    return latest is not None and (
        latest["status"],
        latest["actual_value"],
        latest["reason"],
    ) == (result.status, result.actual_value, result.reason)


def compare_claim(
    claim: Mapping, kpi: Mapping, actuals: Sequence[Mapping]
) -> tuple[str, float | None, str | None]:
    """회사 표현을 같은 연도 표준 실적과 비교해 (결과, 실적, 단위)를 반환한다."""
    metric = actual_metric_of(kpi)
    if metric is None or metric == "dps_growth":
        return "no_standard", None, None

    period = f"{claim['period_year']}-12-31"
    resolved = _resolve_actual(metric, actuals, claim["period_year"], 0, False, period)
    if resolved is None:
        return "no_standard", None, None

    value, unit, _ = resolved
    claimed = claim["claimed_value"] * UNIT_SCALES.get(claim["unit"], 1)
    tolerance = abs(value) * MATCH_TOLERANCE
    return ("match" if abs(claimed - value) <= tolerance else "differs"), value, unit


def compare_all_claims(conn: Connection) -> int:
    claims = conn.execute(
        "SELECT cl.*, k.corp_code, k.metric, k.definition, k.unit AS kpi_unit"
        " FROM company_claims cl JOIN kpi_targets k ON k.id = cl.kpi_target_id"
    ).fetchall()
    for claim in claims:
        kpi = {
            "metric": claim["metric"],
            "unit": claim["kpi_unit"],
            "definition": claim["definition"],
        }
        actuals = conn.execute(
            "SELECT * FROM actuals WHERE corp_code = %s", (claim["corp_code"],)
        ).fetchall()
        comparison, value, unit = compare_claim(claim, kpi, actuals)
        conn.execute(
            "UPDATE company_claims SET comparison = %s, actual_value = %s, actual_unit = %s"
            " WHERE id = %s",
            (comparison, value, unit, claim["id"]),
        )
    return len(claims)


def score_all(conn: Connection) -> int:
    """검수에서 제외되지 않은 KPI를 채점해 바뀐 결과만 scores에 쌓는다."""
    scored = 0
    for kpi in conn.execute(KPI_SQL).fetchall():
        actuals = conn.execute(
            "SELECT * FROM actuals WHERE corp_code = %s", (kpi["corp_code"],)
        ).fetchall()
        result = score_kpi(kpi, int(kpi["disclosed_at"][:4]), actuals)
        if result is None or _is_same_as_latest(conn, kpi["id"], result):
            continue
        conn.execute(
            """
            INSERT INTO scores
                (kpi_target_id, achievement_rate, elapsed_rate, status, reason, actual_value,
                 actual_unit, actual_period, actual_ids)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                kpi["id"],
                result.achievement_rate,
                result.elapsed_rate,
                result.status,
                result.reason,
                result.actual_value,
                result.actual_unit,
                result.actual_period,
                json.dumps(result.actual_ids),
            ),
        )
        scored += 1
    return scored
