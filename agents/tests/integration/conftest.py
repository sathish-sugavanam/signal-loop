"""Integration tests against a real Postgres server.

Set AGENTS_TEST_ADMIN_URL to a superuser URL, for example the Compose database:
    AGENTS_TEST_ADMIN_URL=postgresql://signal_loop:signal_loop@localhost:5432/postgres
Each test gets its own throwaway database with every file in migrations/ applied.
"""

import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo

ADMIN_URL = os.environ.get("AGENTS_TEST_ADMIN_URL")
MIGRATIONS = Path(__file__).resolve().parents[2] / "migrations"


def apply_migrations(url: str) -> None:
    with psycopg.connect(url, autocommit=True) as conn:
        for path in sorted(MIGRATIONS.glob("*.sql")):
            conn.execute(path.read_text())


@pytest.fixture
def admin_url() -> str:
    if not ADMIN_URL:
        pytest.skip("AGENTS_TEST_ADMIN_URL is not set")
    return ADMIN_URL


@pytest.fixture
def database_url(admin_url) -> Iterator[str]:
    name = f"agents_test_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(admin_url, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    url = make_conninfo(admin_url, dbname=name)
    apply_migrations(url)
    try:
        yield url
    finally:
        with psycopg.connect(admin_url, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


@pytest.fixture
def conn(database_url) -> Iterator[psycopg.Connection]:
    with psycopg.connect(database_url, autocommit=True) as conn:
        yield conn
