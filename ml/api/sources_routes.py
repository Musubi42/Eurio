"""FastAPI router for `/sources/status`."""

from fastapi import APIRouter

from . import sources_aggregator

router = APIRouter(prefix="/sources", tags=["sources"])


@router.get("/status")
def sources_status() -> dict:
    return sources_aggregator.build_status()
