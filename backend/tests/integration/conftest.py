"""Starts a throwaway Neo4j container for integration tests.

Tests are skipped (not failed) when Docker is not available.
"""

from collections.abc import Iterator

import pytest

NEO4J_IMAGE = "neo4j:5.26-community"


@pytest.fixture(scope="session")
def neo4j() -> Iterator[dict]:
    try:
        import docker

        docker.from_env().ping()
    except Exception:
        pytest.skip("Docker is not running; skipping integration tests")

    from testcontainers.neo4j import Neo4jContainer

    # GDS and APOC are needed by ring detection and neighbourhood queries.
    container = Neo4jContainer(NEO4J_IMAGE).with_env("NEO4J_PLUGINS", '["apoc", "graph-data-science"]').with_env(
        "NEO4J_dbms_security_procedures_unrestricted", "gds.*,apoc.*"
    )
    with container:
        yield {
            "url": container.get_connection_url(),
            "auth": (container.username, container.password),
        }
