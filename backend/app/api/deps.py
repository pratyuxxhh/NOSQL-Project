"""Shared application services, created once at startup and stored on app.state."""

from dataclasses import dataclass

from fastapi import Request
from neo4j import AsyncDriver

from app.models.settings import RuntimeSettings
from app.services.alerting import AlertService
from app.services.ingestion import IngestionService
from app.services.metrics import Metrics
from app.services.settings_store import SettingsStore
from app.websocket.hub import Hub


@dataclass
class Services:
    driver: AsyncDriver
    settings_store: SettingsStore
    hub: Hub
    metrics: Metrics
    alerts: AlertService
    ingestion: IngestionService

    @property
    def settings(self) -> RuntimeSettings:
        return self.settings_store.current


def get_services(request: Request) -> Services:
    # getattr: lets request validation (401/403/422) run even before startup completes.
    return getattr(request.app.state, "services", None)
