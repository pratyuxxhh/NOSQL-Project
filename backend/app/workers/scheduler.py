"""Periodic ring detection + risk propagation (F5). The interval and algorithm
are admin settings, re-read every cycle, so changes apply without a restart."""

import asyncio
import logging

from app.api.deps import Services
from app.services.flagging import propagate_and_alert
from app.services.ring_detection import detect_rings

logger = logging.getLogger(__name__)


async def run_cycle(s: Services) -> None:
    async with s.ingestion.lock:
        s.metrics.last_propagation = await propagate_and_alert(s.driver, s.settings, s.alerts)
        s.metrics.last_detection = await detect_rings(s.driver, s.settings, s.alerts)


async def detection_loop(s: Services) -> None:
    while True:
        await asyncio.sleep(s.settings.detection.interval_seconds)
        try:
            await run_cycle(s)
        except Exception:
            logger.exception("scheduled detection failed")
