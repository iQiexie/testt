from fastapi import APIRouter, FastAPI

from app.api.routes import docs, health, payments


def setup_routes(app: FastAPI) -> FastAPI:
    router = APIRouter(prefix="/api/v1")

    router.include_router(router=docs.router)
    router.include_router(router=payments.router)

    app.include_router(router=router)
    # Unversioned on purpose: deploy gates and load balancers hit a fixed URL, and it must not move
    # when the API is versioned.
    app.include_router(router=health.router)

    return app
