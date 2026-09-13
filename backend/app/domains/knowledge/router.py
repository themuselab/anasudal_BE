from fastapi import APIRouter, Depends, HTTPException
import asyncpg

from app.core.db import get_conn
from app.core.envelope import EnvelopeRoute
from app.core.errors import ApiError, ErrorCode
from app.domains.knowledge import repository as repo, service
from app.domains.knowledge.schemas import Evidence, SearchRequest, SearchResponse

router = APIRouter(route_class=EnvelopeRoute, prefix="/knowledge", tags=["knowledge"])


@router.post("/search", response_model=SearchResponse, summary="근거 검색 (디버그·평가용)")
async def search(body: SearchRequest, conn: asyncpg.Connection = Depends(get_conn)):
    items = await service.retrieve(conn, body.query, age_months=body.age_months, top_k=body.top_k)
    return SearchResponse(items=items, age_filter_applied=body.age_months is not None)


@router.get("/chunks/{chunk_id}", summary="근거 자료 1건")
async def chunk(chunk_id: str, conn: asyncpg.Connection = Depends(get_conn)):
    r = await repo.get_evidence(conn, chunk_id)
    if r is None:
        raise ApiError(404, ErrorCode.CHUNK_NOT_FOUND, "자료를 찾을 수 없습니다")
    return dict(r)
