import re

PLAN_TITLE = "기업가치제고계획"
PROGRESS_TITLE = "이행현황"
EXCLUDED_TITLES = ("예고", PROGRESS_TITLE)


def is_plan_title(report_name: str) -> bool:
    title = re.sub(r"\s", "", report_name)
    return PLAN_TITLE in title and not any(word in title for word in EXCLUDED_TITLES)


def is_progress_title(report_name: str) -> bool:
    title = re.sub(r"\s", "", report_name)
    return PLAN_TITLE in title and PROGRESS_TITLE in title
