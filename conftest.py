"""Test-wide setup: database tests always run against a separate *_test database.

Database tests delete rows to start clean, so they must never touch the database that
`make collect` fills. Before any test module imports settings, DATABASE_URL is pointed at
`<name>_test` (or TEST_DATABASE_URL if set). The test database is created and migrated on
first use; if Postgres is not running, database tests skip themselves.
"""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError

from firstweek_core.config import Settings, get_settings

ROOT = Path(__file__).parent


def _test_database_url() -> str:
    if explicit := os.environ.get("TEST_DATABASE_URL"):
        return explicit
    url = make_url(Settings().database_url)
    name = url.database or "firstweek"
    return url.set(database=name if name.endswith("_test") else f"{name}_test").render_as_string(
        hide_password=False
    )


TEST_DATABASE_URL = _test_database_url()
os.environ["DATABASE_URL"] = TEST_DATABASE_URL  # env vars override .env in Settings
get_settings.cache_clear()


def _create_and_migrate() -> bool:
    url = make_url(TEST_DATABASE_URL)
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            exists = conn.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": url.database}
            )
            if not exists:
                conn.execute(text(f'CREATE DATABASE "{url.database}"'))
    except OperationalError:
        return False
    finally:
        admin.dispose()

    from alembic import command
    from alembic.config import Config

    config = Config(str(ROOT / "packages/core/alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "packages/core/migrations"))
    command.upgrade(config, "head")
    return True


@pytest.fixture(scope="session", autouse=True)
def test_database() -> Iterator[bool]:
    """True when the migrated test database is available."""
    assert make_url(get_settings().database_url).database.endswith("_test")  # type: ignore[union-attr]
    yield _create_and_migrate()
