from fastapi import FastAPI
from sqlalchemy.orm import sessionmaker

from app.adapters.base import Adapters
from app.api.dependencies.stubs import (
    dependency_adapters,
    dependency_app,
    dependency_services,
    dependency_session_factory,
)
from app.services.base.services import Services


def setup_dependencies(app: FastAPI, session_factory: sessionmaker, adapters: Adapters) -> FastAPI:
    services = Services(session_factory=session_factory, adapters=adapters)

    app.dependency_overrides[dependency_adapters] = lambda: adapters
    app.dependency_overrides[dependency_session_factory] = lambda: session_factory
    app.dependency_overrides[dependency_app] = lambda: app
    app.dependency_overrides[dependency_services] = lambda: services

    return app
