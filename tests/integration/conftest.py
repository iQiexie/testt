import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.adapters.base import Adapters
from app.config.config import PostgresConfig, get_config
from app.init.db import get_session_factory

ROOT = Path(__file__).parent.parent.parent

pytestmark = pytest.mark.integration


@pytest.fixture(scope="session")
async def database() -> None:
    """Создаёт тестовую базу (если нет) и накатывает на неё миграции через alembic."""
    config = PostgresConfig()
    admin_engine = create_async_engine(
        config.dsn.rsplit("/", 1)[0] + "/postgres",
        isolation_level="AUTOCOMMIT",
    )

    try:
        async with admin_engine.connect() as connection:
            query = await connection.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": config.POSTGRES_DB},
            )
            if query.scalar_one_or_none() is None:
                await connection.execute(text(f'CREATE DATABASE "{config.POSTGRES_DB}"'))
    except OSError as e:
        pytest.skip(f"Postgres недоступен ({e}): поднимите `docker compose up -d postgres`")
    finally:
        await admin_engine.dispose()

    subprocess.run(  # noqa: S603
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )


@pytest.fixture(scope="session")
def config(database):  # noqa: ARG001 — нужна только как зависимость: база готова до чтения конфига
    return get_config()


@pytest.fixture(scope="session")
async def db(config):
    session_factory, engine = get_session_factory(config=config.postgres)
    yield session_factory, engine
    await engine.dispose()


@pytest.fixture
def session_factory(db):
    return db[0]


@pytest.fixture(autouse=True)
async def clean_tables(db):
    yield
    async with db[1].begin() as connection:
        await connection.execute(text("TRUNCATE payments, outbox RESTART IDENTITY"))


@pytest.fixture
def adapters(config):
    return Adapters(config=config)
