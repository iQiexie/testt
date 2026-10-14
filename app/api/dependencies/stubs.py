from typing import Annotated, Any, Callable

from fastapi import FastAPI
from fastapi.params import Depends
from sqlalchemy.orm import sessionmaker

from app.adapters.base import Adapters
from app.services.base.services import Services


class Stub:
    def __init__(self, dependency: Callable, **kwargs):
        self._dependency = dependency
        self._kwargs = kwargs

    def __call__(self):
        raise NotImplementedError

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, Stub):
            return self._dependency == other._dependency and self._kwargs == other._kwargs
        else:
            if not self._kwargs:
                return self._dependency == other
            return False

    def __hash__(self):
        if not self._kwargs:
            return hash(self._dependency)
        serial = (
            self._dependency,
            *self._kwargs.items(),
        )
        return hash(serial)


def placeholder() -> None:
    pass


def dependency_session_factory(session_factory: Annotated[sessionmaker, Depends(Stub(sessionmaker))]) -> sessionmaker:
    return session_factory


def dependency_adapters(adapters: Annotated[Adapters, Depends(Stub(Adapters))]) -> Adapters:
    return adapters


def dependency_services(services: Annotated[Services, Depends(Stub(Services))]) -> Services:
    return services


def dependency_app(app: Annotated[FastAPI, Depends(Stub(FastAPI))]) -> FastAPI:
    return app
