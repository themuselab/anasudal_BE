from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class FeedbackReason(BaseModel):
    reason_code: str
    label: str


class FeedbackCreate(BaseModel):
    answer_id: UUID
    rating: Literal["up", "down"]
    reason_code: str | None = None       # down이면 필수 (MISMATCH / UNCLEAR / BAD_RECO) — 라우터에서 코드별 오류


class FeedbackOut(BaseModel):
    feedback_id: UUID
    answer_id: UUID
    rating: str
    reason_code: str | None
