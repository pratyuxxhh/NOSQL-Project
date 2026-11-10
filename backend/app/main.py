"""FastAPI application entry point."""

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app import __version__
from app.api import health
from app.api import v1
from app.api.deps import Services
from app.config import get_settings
from app.db.neo4j import create_driver
from app.db.schema import apply_schema_with_retry
from app.logging_config import configure_logging
from app.security.rate_limit import limiter
from app.services.alerting import AlertService
from app.services.ingestion import IngestionService
from app.services.metrics import Metrics
from app.services.settings_store import SettingsStore
from app.websocket import routes as ws_routes
from app.websocket.hub import Hub
from app.workers.scheduler import detection_loop

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger("fraudmesh")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    driver = create_driver(settings)
    app.state.neo4j_driver = driver
    logger.info("startup", extra={"neo4j_uri": settings.neo4j_uri})
    await apply_schema_with_retry(driver)

    store = SettingsStore(driver)
    with suppress(Exception):  # Neo4j down: keep defaults, /ready reports the problem
        await store.load()
    hub, metrics = Hub(), Metrics()
    alerts = AlertService(driver, hub)
    ingestion = IngestionService(driver, lambda: store.current, alerts, hub, metrics, settings.pii_hash_key)
    services = Services(driver, store, hub, metrics, alerts, ingestion)
    app.state.services = services

    tasks = [asyncio.create_task(ingestion.worker())]
    if settings.scheduler_enabled:
        tasks.append(asyncio.create_task(detection_loop(services)))
    yield
    for task in tasks:
        task.cancel()
    await driver.close()
    logger.info("shutdown")


app = FastAPI(
    title="FraudMesh API",
    description=(
        "Graph-based real-time fraud ring detection and risk propagation. "
        "Dashboard endpoints use a JWT bearer token (POST /api/v1/auth/login); "
        "ingestion and scoring endpoints use an `X-API-Key` header."
    ),
    version=__version__,
    lifespan=lifespan,
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key"],
)

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}


@app.middleware("http")
async def log_requests(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    start = time.perf_counter()
    response = await call_next(request)
    for header, value in SECURITY_HEADERS.items():
        response.headers.setdefault(header, value)
    logger.info(
        "request",
        extra={
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "duration_ms": round((time.perf_counter() - start) * 1000, 2),
        },
    )
    return response


app.include_router(health.router)
app.include_router(v1.router)
app.include_router(ws_routes.router)
