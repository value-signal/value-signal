from datetime import date
from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator


class KpiSource(BaseModel):
    chunk_id: int
    quote: str = Field(min_length=1)


class KpiExtraction(BaseModel):
    """LLM이 계획서에서 뽑아야 하는 KPI 형식.

    이상은 target_min만, 이하는 target_max만, 범위는 둘 다, 단일값은 둘 다 같은 값으로 채운다.
    """

    category: Literal["dividend", "treasury_stock", "shareholder_return", "capital_efficiency"]
    metric: str = Field(min_length=1)
    measure_type: Literal["level", "cumulative"]
    target_min: float | None = None
    target_max: float | None = None
    unit: str = Field(min_length=1)
    deadline: date
    baseline_value: float | None = None
    baseline_period: str | None = None
    definition: str | None = None
    source: KpiSource

    @model_validator(mode="after")
    def check_target(self) -> Self:
        if self.target_min is None and self.target_max is None:
            raise ValueError("target_min과 target_max 중 하나는 필요합니다")
        if (
            self.target_min is not None
            and self.target_max is not None
            and self.target_min > self.target_max
        ):
            raise ValueError("target_min이 target_max보다 큽니다")
        return self


class KpiExtractionResult(BaseModel):
    kpis: list[KpiExtraction]
