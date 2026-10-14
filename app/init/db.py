import functools
import json
import ssl
from typing import Tuple

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.config.config import PostgresConfig
from app.init.base_models import DecimalEncoder


def get_session_factory(config: PostgresConfig) -> Tuple[sessionmaker, AsyncEngine]:
    if config.POSTGRES_SSL:
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        connect_args = {"ssl": ssl_context}
    else:
        connect_args = {}

    engine = create_async_engine(
        url=config.dsn,
        connect_args=connect_args,
        echo=config.POSTGRES_ECHO,
        pool_size=config.POSTGRES_POOL_SIZE,
        max_overflow=config.POSTGRES_MAX_OVERFLOW,
        isolation_level=config.POSTGRES_ISOLATION_LEVEL,
        json_serializer=functools.partial(json.dumps, cls=DecimalEncoder),
        pool_pre_ping=True,
        future=True,
    )

    session_factory = async_sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
        expire_on_commit=False,
    )

    return session_factory, engine
