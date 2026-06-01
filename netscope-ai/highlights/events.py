"""Server-Sent Events — live push to the dashboard.

GET /events/stream  (cookie-authenticated)
  Opens a long-lived text/event-stream. The browser's EventSource receives
  per-tenant events (new analyses from ingest, etc.) the moment they happen,
  replacing client-side polling with server push.
"""
import asyncio
import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from src.api.v1.dep import get_current_context
from src.realtime.broker import broker

router = APIRouter(prefix="/events", tags=["events"])

# How often the generator checks the broker for this tenant's new events.
_POLL_INTERVAL = 1.5


@router.get("/stream")
async def stream(
    request: Request,
    ctx: dict = Depends(get_current_context),
):
    tenant_id = ctx["tenant_id"]

    async def event_gen():
        # Only stream events that arrive AFTER connect (live, not historical).
        last_id = broker.latest_id()
        # Tell EventSource how long to wait before reconnecting.
        yield "retry: 3000\n\n"
        yield 'event: ready\ndata: {"ok":true}\n\n'

        while True:
            if await request.is_disconnected():
                break

            for eid, evt in broker.since(last_id, tenant_id):
                last_id = eid
                yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"

            # heartbeat comment keeps proxies from closing the idle connection
            yield ": ping\n\n"
            await asyncio.sleep(_POLL_INTERVAL)

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # disable nginx buffering if proxied
        },
    )
