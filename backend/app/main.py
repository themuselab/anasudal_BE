from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.cache import available as redis_available, close_redis, open_redis
from app.core.db import close_pool, open_pool
from app.core.errors import install_error_handlers
from app.core.gemini import close_gemini, gemini
from app.domains.chat import summarize
from app.domains.chat.router import router as chat_router
from app.domains.feedback.router import router as feedback_router
from app.domains.institution.router import router as institution_router
from app.domains.knowledge.router import router as knowledge_router
from app.domains.region.router import router as region_router
from app.domains.screening.router import router as screening_router


@asynccontextmanager
async def lifespan(_: FastAPI):
    await open_pool()
    await open_redis()
    yield
    await summarize.drain()          # 돌고 있는 요약 작업을 잠깐 기다린다
    await close_gemini()
    await close_redis()
    await close_pool()


app = FastAPI(
    title="안아수달 API",
    version="0.1.0",
    description="발달재활 기관 매칭 — 근거 기반 답변(RAG) · 기관 추천 · 피드백. 로그인 없음, 대화 원문 미저장.\n\n"
                "모든 응답은 봉투 규격: 성공 `{success: true, data}` · 실패 `{success: false, error: {code, message, details?}}`. "
                "아래 스키마는 `data` 부분이다.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_list,
    allow_methods=["*"],
    allow_headers=["*"],
)

for r in (region_router, institution_router, knowledge_router, chat_router, feedback_router,
          screening_router):
    app.include_router(r, prefix="/v1")


install_error_handlers(app)


@app.get("/health", tags=["ops"])
async def health():
    """키 풀 상태도 같이 — 어느 키가 한도로 쉬는 중인지 (키 값은 해시 앞 8자만)"""
    return {"ok": True, "redis": redis_available(), "gemini": await gemini().snapshot()}
