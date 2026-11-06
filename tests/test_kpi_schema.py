import pytest
from pydantic import ValidationError

from pipeline.extract.schema import KpiExtraction

VALID_KPI = {
    "category": "capital_efficiency",
    "metric": "ROE",
    "measure_type": "level",
    "target_value": 10.0,
    "unit": "%",
    "deadline": "2027-12-31",
    "baseline_value": 7.2,
    "baseline_period": "2024",
    "definition": "지배주주 순이익 기준",
    "source": {"chunk_id": 128, "quote": "2027년까지 ROE 10% 달성"},
}


def test_valid_kpi_passes():
    assert KpiExtraction.model_validate(VALID_KPI).metric == "ROE"


def test_kpi_without_quote_is_rejected():
    invalid = {**VALID_KPI, "source": {"chunk_id": 128, "quote": ""}}
    with pytest.raises(ValidationError):
        KpiExtraction.model_validate(invalid)
