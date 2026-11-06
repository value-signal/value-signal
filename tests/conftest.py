import os
from urllib.parse import urlparse

import psycopg
import pytest

from pipeline.config import settings
from pipeline.db import init_db

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://postgres:test@127.0.0.1:54329/value_signal_test"
)
LOCAL_HOSTS = {"127.0.0.1", "localhost"}


@pytest.fixture
def database(monkeypatch):
    """테스트마다 스키마를 지우므로 로컬 DB에서만 실행한다."""
    assert urlparse(TEST_DATABASE_URL).hostname in LOCAL_HOSTS
    monkeypatch.setattr(settings, "database_url", TEST_DATABASE_URL)
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as conn:
        conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public")
    init_db()
