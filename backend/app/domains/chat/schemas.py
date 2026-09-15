from uuid import UUID

from typing import Literal

from pydantic import BaseModel, Field

from app.domains.institution.schemas import InstitutionCard
from app.domains.knowledge.schemas import Evidence


# ── 세션 ──
class SessionCreate(BaseModel):
    region_id: int | None = None
    child_age_months: int | None = Field(None, ge=0, le=216)


class SessionOut(BaseModel):
    session_id: UUID
    region_id: int | None
    sido: str | None
    sigungu: str | None = None
    child_age_months: int | None
    expires_at: str


class SessionPatch(BaseModel):
    region_id: int | None = None
    child_age_months: int | None = Field(None, ge=0, le=216)


# ── 질문/답변 ──
class AreaPriority(BaseModel):
    area_code: str
    area_name: str
    priority: int = Field(ge=1, le=3)


class AskRequest(BaseModel):
    session_id: UUID
    message: str = Field(min_length=1, max_length=1000)


Intent = Literal["answer", "diagnosis", "out_of_scope", "recommend", "pick_region", "need_context",
                 "screening"]


class AskResponse(BaseModel):
    answer_id: UUID | None               # 안내성 응답(pick_region 등)은 answer 행을 만들지 않아 None
    intent: Intent                       # 프론트 분기 키
    text: str                            # 답변 본문. 키워드·치료영역은 **굵게** (마크다운)
    highlights: list[str]                # 굵게 처리된 단어 목록 (프론트가 직접 렌더링할 때)
    areas: list[AreaPriority]            # 매칭에 쓰는 치료영역
    evidence_count: int                  # "근거 자료 N건 보기"
    fallback_tier: int                   # 1 근거 / 2 부분 / 3 범위 밖 (안내성 응답은 0)
    can_recommend: bool                  # "네, 추천해주세요" 칩 노출 여부
    ask_region: bool                     # True면 시·도/시·군·구 선택 UI 노출 → /chat/recommend 에 region_id
    recommend_for: UUID | None           # 추천 호출 시 쓸 answer_id (최근 근거 답변)
    next_prompts: list[str]              # 후속 칩
    # 조기 관찰(같이 살펴보기)을 이어서 할 수 있는 월령이면 그 값. 아니면 None.
    # 화면은 이 값이 있을 때만 관찰 칩을 띄우고, 값 자체를 /v2/screening/tasks 에 넘긴다.
    screen_age_months: int | None = None


class EvidenceListOut(BaseModel):
    answer_id: UUID
    items: list[Evidence]


# ── 추천 ──
class RecommendRequest(BaseModel):
    session_id: UUID
    answer_id: UUID
    region_id: int | None = None         # 지역 선택 UI 응답(시·군·구). 세션에 저장되고 그 시·도로 추천
    sido: str | None = None              # 시·도만 고른 경우. region_id가 있으면 무시
    max_price: int | None = Field(None, ge=0)


class RecommendedInstitution(InstitutionCard):
    rank: int
    reason: str                          # "왜 이 기관인가"


class RecommendResponse(BaseModel):
    answer_id: UUID
    intro: str                           # "언어치료·감각통합을 함께 볼 수 있는 기관 2곳을 찾았어요"
    items: list[RecommendedInstitution]
    scope_sido: str | None
    browse_hint: str                     # 회의 결정: 둘러보기로 유도하는 멘트


class Prompt(BaseModel):
    prompt_id: int
    text: str
    emoji: str                           # 칩 앞 아이콘 (서버 시드)
