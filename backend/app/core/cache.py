"""Redis — 세 가지 용도. 없으면(REDIS_URL 미설정·장애) 조용히 건너뛰어 API는 계속 동작한다.

  1. 읽기 캐시   : 지역·기관 목록/상세 (MV 데이터, 10분)  → RDS 부하 ↓
  2. 임베딩 캐시 : 같은 질문 문장의 벡터 (7일)             → Gemini 임베딩 호출 ↓ (무료 키 쿼터 보호)
  3. 카운터      : 추천 칩 라운드로빈, /chat/ask IP별 시간당 제한
"""
import hashlib
import json
import logging
from typing import Any, Awaitable, Callable

import redis.asyncio as aioredis

from app.core.config import get_settings

log = logging.getLogger("anasudal.cache")
_r: aioredis.Redis | None = None
PREFIX = "anasudal"


async def open_redis() -> aioredis.Redis | None:
    global _r
    url = get_settings().redis_url
    if not url:
        log.info("REDIS_URL 없음 — 캐시·제한 비활성")
        return None
    client = aioredis.from_url(url, decode_responses=True, socket_connect_timeout=2, socket_timeout=2)
    try:
        await client.ping()
        _r = client
        log.info("redis connected")
    except Exception as e:                      # 연결 실패해도 앱은 뜬다
        log.warning("redis unavailable (%s) — 캐시·제한 비활성", e)
        await client.aclose()
        _r = None
    return _r


async def close_redis() -> None:
    global _r
    if _r is not None:
        await _r.aclose()
        _r = None


def available() -> bool:
    return _r is not None


def key(*parts: Any) -> str:
    return PREFIX + ":" + ":".join(str(p) for p in parts)


def digest(text: str) -> str:
    return hashlib.sha256(text.strip().lower().encode("utf-8")).hexdigest()[:32]


# ── JSON 캐시 ──────────────────────────────────────────────
async def get_json(k: str) -> Any | None:
    if _r is None:
        return None
    try:
        v = await _r.get(k)
        return json.loads(v) if v is not None else None
    except Exception as e:
        log.warning("redis get failed: %s", e)
        return None


async def set_json(k: str, value: Any, ttl: int) -> None:
    if _r is None:
        return
    try:
        await _r.set(k, json.dumps(value, ensure_ascii=False, default=str), ex=ttl)
    except Exception as e:
        log.warning("redis set failed: %s", e)


async def cached(k: str, ttl: int, fn: Callable[[], Awaitable[Any]]) -> Any:
    """캐시 히트면 바로, 미스면 fn() 실행 후 저장. JSON 직렬화 가능한 값만."""
    hit = await get_json(k)
    if hit is not None:
        return hit
    value = await fn()
    await set_json(k, value, ttl)
    return value


# ── 카운터 ────────────────────────────────────────────────
async def incr_window(k: str, window_sec: int) -> int:
    """고정 윈도우 카운터. 첫 증가 시 TTL을 건다. Redis 없으면 0 (= 제한 없음)."""
    if _r is None:
        return 0
    try:
        n = await _r.incr(k)
        if n == 1:
            await _r.expire(k, window_sec)
        return int(n)
    except Exception as e:
        log.warning("redis incr failed: %s", e)
        return 0


async def next_offset(k: str) -> int | None:
    """라운드로빈용 단조 증가 카운터. Redis 없으면 None."""
    if _r is None:
        return None
    try:
        return int(await _r.incr(k))
    except Exception:
        return None
