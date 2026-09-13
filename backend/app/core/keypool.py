"""Gemini API 키 풀 — 여러 키를 돌려 쓰고, 한도(429)를 맞은 키는 쉬게 한다.

쉬는 상태는 Redis 에 둔다. ECS 태스크가 여러 개여도 "이 키는 지금 막혔다"를 같이 알아야
죽은 키를 반복해서 때리지 않는다. Redis 가 없으면 프로세스 안에서만 기억한다(단일 인스턴스 개발용).
"""
import hashlib
import logging
import time

from app.core import cache

log = logging.getLogger("anasudal.keypool")

# 한도 종류별 기본 휴식 시간 — 429 응답에 retryDelay 가 오면 그 값을 우선한다
COOLDOWN_PER_MINUTE = 60
COOLDOWN_PER_DAY = 3600      # 하루 한도는 자정에 풀리지만, 한 시간마다 한 번씩 다시 찔러본다
COOLDOWN_MAX = 6 * 3600


def _tag(key: str) -> str:
    """로그·캐시에 쓰는 키 식별자. 키 자체는 절대 남기지 않는다."""
    return hashlib.sha256(key.encode()).hexdigest()[:8]


class KeyPool:
    """이름 붙은 키 묶음. `pick()` 이 쓸 수 있는 키를 하나 준다."""

    def __init__(self, name: str, keys: list[str]) -> None:
        self.name = name
        self.keys = [k for k in keys if k]
        self._cursor = 0
        self._local: dict[str, float] = {}   # Redis 없을 때: 키 → 풀리는 시각(monotonic)

    def __bool__(self) -> bool:
        return bool(self.keys)

    def _ck(self, key: str) -> str:
        return cache.key("gemkey", self.name, _tag(key))

    async def _resting(self, key: str) -> bool:
        until = self._local.get(key)
        if until is not None and until > time.monotonic():
            return True
        if cache.available():
            return await cache.get_json(self._ck(key)) is not None
        return False

    async def pick(self) -> str | None:
        """쉬는 중이 아닌 키 하나. 전부 쉬는 중이면 None. 호출마다 시작점을 옮겨 고르게 쓴다."""
        if not self.keys:
            return None
        n = len(self.keys)
        start = self._cursor % n
        self._cursor = (self._cursor + 1) % n
        for i in range(n):
            key = self.keys[(start + i) % n]
            if not await self._resting(key):
                return key
        return None

    async def rest(self, key: str, seconds: int, reason: str = "") -> None:
        """이 키를 seconds 동안 빼둔다."""
        sec = max(5, min(int(seconds), COOLDOWN_MAX))
        self._local[key] = time.monotonic() + sec
        if cache.available():
            await cache.set_json(self._ck(key), {"reason": reason[:120]}, sec)
        log.warning("gemini key %s/%s 휴식 %ds — %s", self.name, _tag(key), sec, reason[:120])

    async def snapshot(self) -> dict[str, object]:
        """헬스체크용 — 몇 개 중 몇 개가 지금 쓸 수 있는지. 키 값은 노출하지 않는다."""
        states = []
        for k in self.keys:
            states.append({"key": _tag(k), "resting": await self._resting(k)})
        return {
            "total": len(self.keys),
            "available": sum(1 for s in states if not s["resting"]),
            "keys": states,
        }
