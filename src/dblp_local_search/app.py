"""HTTP application; no background import jobs inside API worker processes."""

import secrets
import sqlite3
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from dblp_local_search.api.limits import BodyLimitMiddleware
from dblp_local_search.config import Settings
from dblp_local_search.search import service
from dblp_local_search.search.models import Search
from dblp_local_search.storage.database import NotReady, QueryTimedOut


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    app = FastAPI(title="DBLP Local Search", version="0.1.0", docs_url="/docs")

    app.add_middleware(BodyLimitMiddleware)

    def auth(authorization: Annotated[str | None, Header()] = None) -> None:
        if not settings.api_token:
            raise HTTPException(503, "DBLP_API_TOKEN is not configured")
        expected = f"Bearer {settings.api_token}".encode()
        if not authorization or not secrets.compare_digest(
            authorization.encode(), expected
        ):
            raise HTTPException(401, "Missing or invalid Bearer token")

    @app.exception_handler(NotReady)
    async def not_ready(request: Request, error: Exception) -> JSONResponse:
        return JSONResponse({"detail": str(error)}, status_code=503)

    @app.exception_handler(QueryTimedOut)
    async def query_timeout(request: Request, error: Exception) -> JSONResponse:
        return JSONResponse({"detail": str(error)}, status_code=503)

    @app.exception_handler(ValueError)
    async def invalid(request: Request, error: Exception) -> JSONResponse:
        return JSONResponse({"detail": str(error)}, status_code=422)

    @app.exception_handler(sqlite3.DatabaseError)
    async def database_error(request: Request, error: Exception) -> JSONResponse:
        return JSONResponse(
            {"detail": "Dataset database error; inspect server logs"}, status_code=503
        )

    register_routes(app, settings, auth)
    return app


def register_routes(
    app: FastAPI, settings: Settings, auth: Callable[..., None]
) -> None:
    protected = [Depends(auth)]

    @app.get("/health/live")
    def live() -> dict[str, str]:
        return {"status": "alive"}

    @app.get("/health/ready")
    def ready() -> dict[str, str]:
        service.dataset(settings)
        return {"status": "ready"}

    @app.get("/v1/dataset", dependencies=protected)
    def dataset() -> dict[str, Any]:
        return service.dataset(settings)

    @app.post("/v1/papers/search", dependencies=protected)
    def search(body: Search) -> dict[str, Any]:
        return service.search(settings, body)

    @app.get("/v1/papers/lookup", dependencies=protected)
    def lookup(
        key: Annotated[str | None, Query(max_length=1000)] = None,
        doi: Annotated[str | None, Query(max_length=1000)] = None,
    ) -> dict[str, Any]:
        if bool(key) == bool(doi):
            raise HTTPException(422, "Specify exactly one of key or doi")
        return service.lookup(settings, key, doi.casefold() if doi else None)

    @app.get("/v1/authors/search", dependencies=protected)
    def authors(
        name: Annotated[str, Query(min_length=1, max_length=300)],
        page_size: Annotated[int, Query(ge=1, le=100)] = 100,
        cursor: Annotated[str | None, Query(max_length=8192)] = None,
    ) -> dict[str, Any]:
        return service.authors(settings, name, page_size, cursor)

    @app.get("/v1/authors/{author_id}/papers", dependencies=protected)
    def author_papers(
        author_id: int,
        page_size: Annotated[int, Query(ge=1, le=100)] = 100,
        cursor: Annotated[str | None, Query(max_length=8192)] = None,
    ) -> dict[str, Any]:
        return service.search(
            settings,
            Search(
                author_id=author_id,
                page_size=page_size,
                cursor=cursor,
            ),
        )
