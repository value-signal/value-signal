-- Value Signal 스키마. scores는 pipeline/scoring만 기록한다.

CREATE TABLE IF NOT EXISTS companies (
    corp_code  TEXT PRIMARY KEY,
    stock_code TEXT NOT NULL UNIQUE,
    corp_name  TEXT NOT NULL,
    market     TEXT NOT NULL CHECK (market IN ('KOSPI', 'KOSDAQ')),
    is_low_pbr  INTEGER NOT NULL DEFAULT 0 CHECK (is_low_pbr IN (0, 1))
);

CREATE TABLE IF NOT EXISTS disclosures (
    rcept_no        TEXT PRIMARY KEY,
    corp_code       TEXT NOT NULL REFERENCES companies (corp_code),
    report_name     TEXT NOT NULL,
    disclosure_type TEXT NOT NULL,
    disclosed_at    TEXT NOT NULL,
    source_url      TEXT NOT NULL,
    raw_path        TEXT,
    collected_at    TEXT NOT NULL DEFAULT (datetime('now')),
    extracted_at    TEXT
);

CREATE TABLE IF NOT EXISTS document_chunks (
    id          INTEGER PRIMARY KEY,
    rcept_no    TEXT NOT NULL REFERENCES disclosures (rcept_no),
    chunk_index INTEGER NOT NULL,
    page        INTEGER,
    section     TEXT,
    text        TEXT NOT NULL,
    UNIQUE (rcept_no, chunk_index)
);

CREATE TABLE IF NOT EXISTS kpi_targets (
    id              INTEGER PRIMARY KEY,
    corp_code       TEXT NOT NULL REFERENCES companies (corp_code),
    chunk_id        INTEGER NOT NULL REFERENCES document_chunks (id),
    category        TEXT NOT NULL
                    CHECK (category IN ('dividend', 'treasury_stock', 'shareholder_return',
                                        'capital_efficiency')),
    metric          TEXT NOT NULL,
    measure_type    TEXT NOT NULL CHECK (measure_type IN ('level', 'cumulative')),
    target_min      REAL,
    target_max      REAL,
    unit            TEXT NOT NULL,
    deadline        TEXT NOT NULL,
    baseline_value  REAL,
    baseline_period TEXT,
    definition      TEXT,
    quote           TEXT NOT NULL,
    start_year      INTEGER,
    unscorable_reason TEXT,
    review_note     TEXT,
    review_status   TEXT NOT NULL DEFAULT 'pending'
                    CHECK (review_status IN ('pending', 'approved', 'rejected')),
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    CHECK (target_min IS NOT NULL OR target_max IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS actuals (
    id         INTEGER PRIMARY KEY,
    corp_code  TEXT NOT NULL REFERENCES companies (corp_code),
    metric     TEXT NOT NULL,
    period_end TEXT NOT NULL,
    value      REAL NOT NULL,
    unit       TEXT NOT NULL,
    rcept_no   TEXT NOT NULL,
    UNIQUE (corp_code, metric, period_end, rcept_no)
);

-- 이력을 쌓아 직전 값과 비교한다.
CREATE TABLE IF NOT EXISTS scores (
    id               INTEGER PRIMARY KEY,
    kpi_target_id    INTEGER NOT NULL REFERENCES kpi_targets (id),
    achievement_rate REAL,
    elapsed_rate     REAL,
    status           TEXT NOT NULL
                     CHECK (status IN ('achieved', 'on_track', 'delayed', 'unverifiable')),
    reason           TEXT,
    actual_value     REAL,
    actual_unit      TEXT,
    actual_period    TEXT,
    actual_ids       TEXT NOT NULL DEFAULT '[]',
    evaluated_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS subscriptions (
    email     TEXT NOT NULL,
    corp_code TEXT NOT NULL REFERENCES companies (corp_code),
    PRIMARY KEY (email, corp_code)
);

CREATE TABLE IF NOT EXISTS alerts (
    id         INTEGER PRIMARY KEY,
    email      TEXT NOT NULL,
    corp_code  TEXT NOT NULL REFERENCES companies (corp_code),
    kind       TEXT NOT NULL CHECK (kind IN ('new_disclosure', 'score_change')),
    message    TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    sent_at    TEXT
);

CREATE INDEX IF NOT EXISTS idx_chunks_rcept ON document_chunks (rcept_no);
CREATE INDEX IF NOT EXISTS idx_kpi_corp ON kpi_targets (corp_code);
CREATE INDEX IF NOT EXISTS idx_scores_kpi ON scores (kpi_target_id, evaluated_at);
