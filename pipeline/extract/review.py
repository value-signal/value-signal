import csv
import sqlite3

from pipeline.config import ROOT_DIR

REVIEWS_PATH = ROOT_DIR / "data" / "kpi_reviews.csv"

MATCH_SQL = """
SELECT k.id FROM kpi_targets k JOIN companies c USING (corp_code)
WHERE c.stock_code = ? AND k.metric = ? AND coalesce(k.target_min, k.target_max) = ?
"""


def apply_reviews(conn: sqlite3.Connection) -> int:
    """사람이 검수한 결과를 반영한다. DB를 다시 만들어도 같은 결과가 나오도록 파일로 관리한다."""
    with REVIEWS_PATH.open(encoding="utf-8", newline="") as file:
        reviews = list(csv.DictReader(file))

    applied = 0
    for review in reviews:
        row = conn.execute(
            MATCH_SQL, (review["stock_code"], review["metric"], float(review["target"]))
        ).fetchone()
        if row is None:
            continue
        reason = review["reason"] or None
        conn.execute(
            """
            UPDATE kpi_targets SET
                metric = coalesce(?, metric),
                start_year = coalesce(?, start_year),
                review_status = CASE WHEN ? = 'reject' THEN 'rejected' ELSE review_status END,
                unscorable_reason = CASE WHEN ? = 'unscorable' THEN ? ELSE unscorable_reason END,
                review_note = ?
            WHERE id = ?
            """,
            (
                review["new_metric"] or None,
                review["start_year"] or None,
                review["action"],
                review["action"],
                reason,
                reason,
                row["id"],
            ),
        )
        applied += 1
    return applied
