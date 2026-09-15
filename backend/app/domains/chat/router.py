from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
import asyncpg

from app.core import cache
from app.core.config import get_settings
from app.core.db import get_conn
from app.core.envelope import EnvelopeRoute
from app.core.errors import ApiError, ErrorCode
from app.domains.chat import repository as repo, service
from app.domains.chat.schemas import (AskRequest, AskResponse, EvidenceListOut, Prompt, RecommendRequest,
                                      RecommendResponse, SessionCreate, SessionOut, SessionPatch)

router = APIRouter(route_class=EnvelopeRoute, tags=["chat"])


# ── 세션 ──
@router.post("/sessions", response_model=SessionOut, status_code=201, summary="익명 세션 발급")
async def create_session(body: SessionCreate, conn: asyncpg.Connection = Depends(get_conn)):
    return await service.create_session(conn, body.region_id, body.child_age_months)


@router.get("/sessions/{session_id}", response_model=SessionOut)
async def get_session(session_id: UUID, conn: asyncpg.Connection = Depends(get_conn)):
    return await service.get_session(conn, session_id)


@router.patch("/sessions/{session_id}", response_model=SessionOut, summary="위치·월령 설정")
async def patch_session(session_id: UUID, body: SessionPatch, conn: asyncpg.Connection = Depends(get_conn)):
    await service.get_session(conn, session_id)
    await repo.patch_session(conn, session_id, body.region_id, body.child_age_months)
    return await service.get_session(conn, session_id)


# ── 채팅 ──
@router.get("/chat/prompts", response_model=list[Prompt], summary="첫 화면 추천 질문 칩 (호출마다 회전)")
async def prompts(conn: asyncpg.Connection = Depends(get_conn)):
    return await service.rotating_prompts(conn)


async def _rate_limit(request: Request) -> None:
    """로그인이 없으므로 IP 기준. Redis 없으면 통과."""
    ip = request.client.host if request.client else "unknown"
    limit = get_settings().ask_rate_limit_per_hour
    n = await cache.incr_window(cache.key("rl", "ask", ip), 3600)
    if n > limit:
        raise ApiError(429, ErrorCode.RATE_LIMITED, f"질문이 너무 많아요. 잠시 후 다시 시도해주세요. (시간당 {limit}회)")


@router.post("/chat/ask", response_model=AskResponse, summary="질문 → 근거 기반 답변")
async def ask(body: AskRequest, request: Request, conn: asyncpg.Connection = Depends(get_conn)):
    await _rate_limit(request)
    return await service.ask(conn, body.session_id, body.message)


@router.post("/chat/ask/stream", summary="질문 → 답변 (SSE 스트리밍)",
             responses={200: {"content": {"text/event-stream": {"schema": {"type": "string"}}},
                             "description": "event: meta {evidence_count} · delta {text}* · done {AskResponse} | error {code,message}"}})
async def ask_stream(body: AskRequest, request: Request):
    await _rate_limit(request)
    return StreamingResponse(
        service.ask_stream(body.session_id, body.message),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/chat/answers/{answer_id}/evidence", response_model=EvidenceListOut, summary="근거 자료 N건")
async def evidence(answer_id: UUID, conn: asyncpg.Connection = Depends(get_conn)):
    return await service.evidence(conn, answer_id)


@router.post("/chat/recommend", response_model=RecommendResponse, summary="'네, 추천해주세요' → 기관 3곳")
async def recommend(body: RecommendRequest, conn: asyncpg.Connection = Depends(get_conn)):
    return await service.recommend(conn, session_id=body.session_id, answer_id=body.answer_id,
                                   area_codes=body.area_codes, region_id=body.region_id,
                                   sido=body.sido, max_price=body.max_price)
