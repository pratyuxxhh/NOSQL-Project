"""Audit log of analyst and admin actions (flag, confirm ring, resolve alert,
change settings ...), stored as :AuditLog nodes."""

import json
from typing import Any

from neo4j import AsyncDriver

from app.security.rbac import CurrentUser


async def audit(
    driver: AsyncDriver, user: CurrentUser | str, action: str, target: str, details: dict[str, Any] | None = None
) -> None:
    actor = user if isinstance(user, str) else user.username
    await driver.execute_query(
        "CREATE (:AuditLog {id: randomUUID(), at: datetime(), actor: $actor, action: $action, "
        "target: $target, details: $details})",
        actor=actor,
        action=action,
        target=target,
        details=json.dumps(details or {}, default=str),
    )
