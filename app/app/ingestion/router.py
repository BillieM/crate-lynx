from fastapi import APIRouter, Request


router = APIRouter()


@router.get("/ingest/status")
async def ingest_status(request: Request) -> dict[str, object]:
    return {"status": "ok", **request.app.state.ingestion_status.snapshot()}
