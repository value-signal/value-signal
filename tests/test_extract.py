import pytest

from pipeline.collect.disclosures import is_plan_title
from pipeline.db import connect, init_db
from pipeline.extract import chunking
from pipeline.extract.chunking import MAX_CHUNK_CHARS, html_to_lines, split_lines
from pipeline.extract.kpi import process_disclosure

RAW = """<html><head><style>.a { color: red; }</style></head><body>
<p>5.ROE 제고</p><p>- 2030년 연결 ROE 25% 이상 달성 목표</p>
<p>- ROE &gt; COE 유지</p><p>직전 사업연도 배당성향 115</p></body></html>"""


def make_kpi(chunk_id, quote="- 2030년 연결 ROE 25% 이상 달성 목표", **overrides):
    return {
        "category": "capital_efficiency",
        "metric": "ROE",
        "measure_type": "level",
        "target_min": 25,
        "target_max": None,
        "unit": "%",
        "deadline": "2030-12-31",
        "source": {"chunk_id": chunk_id, "quote": quote},
        **overrides,
    }


class FakeLLM:
    def __init__(self, build_kpis):
        self.build_kpis = build_kpis

    def complete_json(self, system, user, schema):
        return {"kpis": self.build_kpis(int(user.split("[조각 ")[1].split("]")[0]))}


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(chunking, "ROOT_DIR", tmp_path)
    (tmp_path / "plan.xml").write_text(RAW, encoding="utf-8")
    db_path = tmp_path / "test.sqlite"
    init_db(db_path)
    with connect(db_path) as connection:
        connection.execute(
            "INSERT INTO companies (corp_code, stock_code, corp_name, market)"
            " VALUES ('c1', '000001', '테스트', 'KOSDAQ')"
        )
        connection.execute(
            "INSERT INTO disclosures (rcept_no, corp_code, report_name, disclosure_type,"
            " disclosed_at, source_url, raw_path)"
            " VALUES ('r1', 'c1', '계획', 'plan', '20260701', 'url', 'plan.xml')"
        )
        yield connection


def saved_metrics(conn):
    return [row["metric"] for row in conn.execute("SELECT metric FROM kpi_targets")]


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("기업가치제고계획(자율공시)", True),
        ("기업가치 제고 계획(자율공시)   (2026년)", True),
        ("[기재정정]기업가치제고계획(자율공시)", True),
        ("기업가치제고계획(자율공시)   (2025년 이행현황)", False),
        ("기업가치제고계획예고(안내공시)", False),
        ("주주총회소집결의", False),
    ],
)
def test_is_plan_title(title, expected):
    assert is_plan_title(title) is expected


def test_html_to_lines_removes_style_and_decodes_entities():
    lines = html_to_lines(RAW)

    assert "- ROE > COE 유지" in lines
    assert not any("color" in line for line in lines)


def test_split_lines_keeps_lines_whole_and_within_limit():
    lines = ["가" * 900, "나" * 900, "다" * 100]

    chunks = split_lines(lines)

    assert chunks == [lines[0], f"{lines[1]}\n{lines[2]}"]
    assert all(len(chunk) <= MAX_CHUNK_CHARS for chunk in chunks)


def test_process_disclosure_saves_verified_kpi(conn):
    process_disclosure(conn, FakeLLM(lambda chunk_id: [make_kpi(chunk_id)]), "r1")

    assert saved_metrics(conn) == ["ROE"]
    assert conn.execute("SELECT review_status FROM kpi_targets").fetchone()[0] == "pending"


@pytest.mark.parametrize(
    "build_kpi",
    [
        pytest.param(lambda chunk_id: make_kpi(chunk_id, quote="없는 문장 25%"), id="fake-quote"),
        pytest.param(lambda chunk_id: make_kpi(chunk_id, target_min=30), id="wrong-number"),
        pytest.param(lambda chunk_id: make_kpi(chunk_id + 999), id="unknown-chunk"),
        pytest.param(lambda chunk_id: make_kpi(chunk_id, target_min=None), id="no-target"),
        pytest.param(
            lambda chunk_id: make_kpi(
                chunk_id, quote="직전 사업연도 배당성향 115", target_min=11.5
            ),
            id="partial-number",
        ),
    ],
)
def test_process_disclosure_discards_unverified_kpi(conn, build_kpi):
    process_disclosure(conn, FakeLLM(lambda chunk_id: [build_kpi(chunk_id)]), "r1")

    assert saved_metrics(conn) == []


def test_process_disclosure_keeps_valid_kpi_when_another_is_invalid(conn):
    llm = FakeLLM(lambda chunk_id: [make_kpi(chunk_id), make_kpi(chunk_id, quote="없는 문장 25%")])

    process_disclosure(conn, llm, "r1")

    assert saved_metrics(conn) == ["ROE"]
