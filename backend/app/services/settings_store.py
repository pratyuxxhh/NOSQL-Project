"""Loads and saves RuntimeSettings in Neo4j (a single :Config {id: 'runtime'} node)."""

from neo4j import AsyncDriver

from app.models.settings import RuntimeSettings


class SettingsStore:
    def __init__(self, driver: AsyncDriver) -> None:
        self.driver = driver
        self.current = RuntimeSettings()

    async def load(self) -> RuntimeSettings:
        records, _, _ = await self.driver.execute_query(
            "MATCH (c:Config {id: 'runtime'}) RETURN c.json AS json"
        )
        if records and records[0]["json"]:
            self.current = RuntimeSettings.model_validate_json(records[0]["json"])
        return self.current

    async def save(self, settings: RuntimeSettings) -> RuntimeSettings:
        await self.driver.execute_query(
            "MERGE (c:Config {id: 'runtime'}) SET c.json = $json, c.updated_at = datetime()",
            json=settings.model_dump_json(),
        )
        self.current = settings
        return settings
