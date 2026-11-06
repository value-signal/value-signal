import pytest
from pydantic import ValidationError

from pipeline.extract.schema import KpiExtraction

VALID_KPI = {
    "category": "capital_efficiency",
    "metric": "ROE",
    "measure_type": "level",
    "target_min": 10.0,
    "target_max": 10.0,
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


def test_range_and_one_sided_targets_pass():
    assert KpiExtraction.model_validate({**VALID_KPI, "target_min": 35, "target_max": 40})
    assert KpiExtraction.model_validate({**VALID_KPI, "target_min": 25, "target_max": None})
    assert KpiExtraction.model_validate({**VALID_KPI, "target_min": None, "target_max": 100})


@pytest.mark.parametrize(("target_min", "target_max"), [(None, None), (40, 35)])
def test_missing_or_reversed_target_is_rejected(target_min, target_max):
    with pytest.raises(ValidationError):
        KpiExtraction.model_validate(
            {**VALID_KPI, "target_min": target_min, "target_max": target_max}
        )
