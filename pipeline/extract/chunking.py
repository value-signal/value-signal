
from bs4 import BeautifulSoup

from pipeline.config import ROOT_DIR
from pipeline.db import Connection

MAX_CHUNK_CHARS = 1500


def html_to_lines(raw: str) -> list[str]:
    soup = BeautifulSoup(raw, "lxml")
    for tag in soup(["style", "script"]):
        tag.decompose()
    return [" ".join(line.split()) for line in soup.get_text("\n", strip=True).splitlines()]


def split_lines(lines: list[str]) -> list[str]:
    """인용문이 조각 경계에서 잘리지 않도록 줄 단위로 묶는다."""
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for line in filter(None, lines):
        if current and size + len(line) > MAX_CHUNK_CHARS:
            chunks.append("\n".join(current))
            current, size = [], 0
        current.append(line)
        size += len(line) + 1
    if current:
        chunks.append("\n".join(current))
    return chunks


def chunk_disclosure(conn: Connection, rcept_no: str) -> None:
    """공시 원문을 쪼개 document_chunks에 저장한다."""
    if conn.execute(
        "SELECT 1 FROM document_chunks WHERE rcept_no = %s LIMIT 1", (rcept_no,)
    ).fetchone():
        return

    row = conn.execute(
        "SELECT raw_path FROM disclosures WHERE rcept_no = %s", (rcept_no,)
    ).fetchone()
    raw = (ROOT_DIR / row["raw_path"]).read_text(encoding="utf-8")
    conn.cursor().executemany(
        "INSERT INTO document_chunks (rcept_no, chunk_index, text) VALUES (%s, %s, %s)",
        [
            (rcept_no, index, text)
            for index, text in enumerate(split_lines(html_to_lines(raw)))
        ],
    )
