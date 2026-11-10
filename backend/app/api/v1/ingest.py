"""Ingestion and synchronous scoring for transaction-processing services
(F2, F13). Authenticated by API key, not by user login."""

from fastapi import APIRouter, Depends, Request, status

from app.api.deps import Services, get_services
from app.models.events import BatchIn, ScoreResult, TransactionEvent
from app.security.api_keys import ApiClient, api_client

router = APIRouter(tags=["ingestion"])


@router.post("/ingest/transaction", status_code=status.HTTP_202_ACCEPTED)
async def ingest_transaction(
    event: TransactionEvent,
    client: ApiClient = Depends(api_client),
    s: Services = Depends(get_services),
) -> dict:
    """Queue one event. Processing (graph update, scoring, alerts) happens in the background."""
    await s.ingestion.enqueue(event)
    return {"accepted": 1, "queue_depth": s.ingestion.queue.qsize()}


async def _count_events(request: Request) -> None:
    # Charge the batch's size against the key's rate limit (checked in api_client).
    body = await request.json()
    request.state.event_count = max(1, len(body.get("events", [])))


@router.post("/ingest/batch", status_code=status.HTTP_202_ACCEPTED,
             dependencies=[Depends(_count_events)])
async def ingest_batch(
    batch: BatchIn,
    client: ApiClient = Depends(api_client),
    s: Services = Depends(get_services),
) -> dict:
    for event in batch.events:
        await s.ingestion.enqueue(event)
    return {"accepted": len(batch.events), "queue_depth": s.ingestion.queue.qsize()}


@router.post("/score", response_model=ScoreResult)
async def score(
    event: TransactionEvent,
    client: ApiClient = Depends(api_client),
    s: Services = Depends(get_services),
) -> ScoreResult:
    """Process the transaction now and return ALLOW / REVIEW / BLOCK with the reasons."""
    return await s.ingestion.process(event)
