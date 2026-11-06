from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class KpiSource(BaseModel):
    chunk_id: int
    quote: str = Field(min_length=1)


class KpiExtraction(BaseModel):
    """LLM이 계획서에서 뽑아야 하는 KPI 형식."""

    category: Literal["dividend", "treasury_stock", "capital_efficiency"]
    metric: str = Field(min_length=1)
    measure_type: Literal["level", "cumulative"]
    target_value: float
    unit: str = Field(min_length=1)
    deadline: date
    baseline_value: float | None = None
    baseline_period: str | None = None
    definition: str | None = None
    source: KpiSource
