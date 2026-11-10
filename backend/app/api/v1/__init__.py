"""Versioned REST API (/api/v1)."""

from fastapi import APIRouter

from app.api.v1 import admin, alerts, auth, graph, ingest, rings, risk, stats

router = APIRouter(prefix="/api/v1")
for module in (auth, ingest, graph, rings, risk, alerts, stats, admin):
    router.include_router(module.router)
