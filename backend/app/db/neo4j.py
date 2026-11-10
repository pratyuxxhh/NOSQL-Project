"""Neo4j driver lifecycle and FastAPI dependency."""

from fastapi import Request
from neo4j import AsyncDriver, AsyncGraphDatabase

from app.config import Settings


def create_driver(settings: Settings) -> AsyncDriver:
    # Creating the driver does not connect; connections open lazily on first query.
    return AsyncGraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
        # Query notifications (deprecations, unknown labels on an empty graph) would
        # flood the logs; real errors still raise exceptions.
        notifications_min_severity="OFF",
    )


def get_driver(request: Request) -> AsyncDriver:
    """FastAPI dependency returning the app-wide driver created at startup."""
    return request.app.state.neo4j_driver
