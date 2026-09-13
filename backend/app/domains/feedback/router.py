from fastapi import APIRouter, Depends, HTTPException
import asyncpg

from app.core import cache
from app.core.db import get_conn
from app.core.envelope import EnvelopeRoute
from app.core.errors import ApiError, ErrorCode
from app.domains.feedback import repository as repo
from app.domains.feedback.schemas import FeedbackCreate, FeedbackOut, FeedbackReason

router = APIRouter(route_class=EnvelopeRoute, prefix="/feedback", tags=["feedback"])


@router.get("/reasons", response_model=list[FeedbackReason], summary="👎 사유 3종")
async def reasons(conn: asyncpg.Connection = Depends(get_conn)):
    return [dict(r) for r in await repo.list_reasons(conn)]


@router.post("", response_model=FeedbackOut, status_code=201, summary="👍/👎 저장 (개인정보 없음)")
async def create(body: FeedbackCreate, conn: asyncpg.Connection = Depends(get_conn)):
    if body.rating == "down" and not body.reason_code:
        raise ApiError(400, ErrorCode.FEEDBACK_REASON_REQUIRED, "👎 에는 사유 선택이 필요합니다")
    if body.reason_code:
        valid = {x["reason_code"] for x in await repo.list_reasons(conn)}
        if body.reason_code not in valid:
            raise ApiError(400, ErrorCode.INVALID_REASON_CODE, "사유 코드가 올바르지 않습니다",
                           {"allowed": sorted(valid)})
    try:
        r = await repo.upsert(conn, body.answer_id, body.rating, body.reason_code)
    except asyncpg.ForeignKeyViolationError:
        raise ApiError(404, ErrorCode.ANSWER_NOT_FOUND, "답변을 찾을 수 없습니다")
    # 학습 표본: 요약 질문 + 답변 본문(Redis에 남아 있으면) + 평가·사유 + 영역·근거·추천
    conv = await cache.get_json(cache.key("conv", body.answer_id)) or {}
    await repo.upsert_training_sample(conn, body.answer_id, body.rating, body.reason_code,
                                      conv.get("answer"), conv.get("age"))
    return dict(r)
