from fastapi import FastAPI


def setup_openapi(app: FastAPI) -> FastAPI:
    app.openapi_url = "/api/v1/openapi.json"
    return app
