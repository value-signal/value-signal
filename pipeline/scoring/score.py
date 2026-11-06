import sqlite3
from dataclasses import dataclass
from typing import Literal

Status = Literal["achieved", "on_track", "delayed", "unverifiable"]


@dataclass(frozen=True)
class ScoreResult:
    status: Status
    achievement_rate: float | None
    elapsed_rate: float | None
    reason: str | None
    actual_ids: list[int]


def score_kpi(kpi: sqlite3.Row, actuals: list[sqlite3.Row], evaluated_on: str) -> ScoreResult:
    """달성률과 기간 경과율로 상태를 정한다. 기간 시작일은 계획 공시일로 본다.

    달성률 = (실적 - 기준값) / (목표 - 기준값)
    기간 경과율 = (평가일 - 시작일) / (기한 - 시작일)

    이 패키지에서는 LLM을 호출하지 않는다. 지표 정의가 다르면 unverifiable을 반환한다.
    """
    raise NotImplementedError
