"""Gemini REST 클라이언트 — 임베딩(검색용)·생성(답변용)·요약(백그라운드) 세 역할.
SDK 대신 httpx 로 직접 호출: 의존성이 가볍고 응답 스키마가 명시적이다.

키는 두 묶음으로 나눈다.
  · 답변·임베딩 = 사용자가 기다리는 경로. 여러 키를 돌려 쓰고 한도에 걸린 키는 바로 건너뛴다.
  · 요약        = 백그라운드로 DB 에 쌓는 용도. 답변 쿼터를 갉아먹지 않게 키를 분리한다.
"""
import asyncio
import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, TypeVar

import httpx

from app.core import cache
from app.core.config import get_settings
from app.core.keypool import COOLDOWN_PER_DAY, COOLDOWN_PER_MINUTE, KeyPool

log = logging.getLogger("anasudal.gemini")
_BASE = "https://generativelanguage.googleapis.com/v1beta"
T = TypeVar("T")


class GeminiError(RuntimeError):
    def __init__(self, msg: str, rate_limited: bool = False, exhausted: bool = False,
                 retry_after: int = 0, busy: bool = False) -> None:
        super().__init__(msg)
        self.rate_limited = rate_limited    # 429 를 맞았다
        self.exhausted = exhausted          # 풀의 키가 전부 쉬는 중 → 사람 손이 필요하거나 대체 응답으로
        self.retry_after = retry_after      # 초
        self.busy = busy                    # 503 등 모델 과부하. 우리 잘못이 아니고 곧 풀린다


@dataclass
class _Limit:
    """429 응답에서 읽어낸 한도 정보"""
    retry_after: int
    daily: bool
    message: str


def _read_limit(data: dict[str, Any]) -> _Limit:
    """RetryInfo 가 있으면 그 값을, 없으면 한도 종류(분/일)로 휴식 시간을 정한다."""
    err = data.get("error") or {}
    details = err.get("details") or []
    retry_after = 0
    daily = False
    for d in details:
        t = str(d.get("@type", ""))
        if t.endswith("RetryInfo"):
            m = re.match(r"(\d+(?:\.\d+)?)s", str(d.get("retryDelay", "")))
            if m:
                retry_after = int(float(m.group(1))) + 1
        elif t.endswith("QuotaFailure"):
            for v in d.get("violations") or []:
                if "PerDay" in str(v.get("quotaId", "")):
                    daily = True
    if not retry_after:
        retry_after = COOLDOWN_PER_DAY if daily else COOLDOWN_PER_MINUTE
    return _Limit(retry_after=retry_after, daily=daily, message=str(err.get("message", ""))[:200])


def _is_429(status: int, data: dict[str, Any]) -> bool:
    return status == 429 or (data.get("error") or {}).get("code") == 429


# 모델이 붐빌 때 오는 것들. 한도(429)와 다르다 — 키를 쉬게 할 이유가 없고,
# 잠깐 뒤에 다시 부르면 대개 된다. 그냥 올리면 사용자에게 "답변 생성에 실패했어요"가 나간다.
_TRANSIENT = {500, 502, 503, 504}
_BACKOFF = (0.6, 1.5, 3.0)      # 초. 합쳐도 5초 남짓 — 사용자가 기다리는 경로라 길게 못 끈다


def _is_transient(status: int, data: dict[str, Any]) -> bool:
    return status in _TRANSIENT or (data.get("error") or {}).get("code") in _TRANSIENT


class _RateLimited(Exception):
    def __init__(self, limit: _Limit) -> None:
        self.limit = limit


class _Transient(Exception):
    """일시적 과부하. 같은 키로 다시 해도 되지만, 이왕이면 다음 키로 넘긴다."""
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class Gemini:
    def __init__(self) -> None:
        s = get_settings()
        self.embed_model = s.gemini_embed_model
        self.gen_model = s.gemini_gen_model
        self.dim = s.embed_dim
        self.answers = KeyPool("answer", s.answer_keys)
        self.summaries = KeyPool("summary", s.summary_keys)
        self._http = httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0))

    async def aclose(self) -> None:
        await self._http.aclose()

    # ── 키를 바꿔가며 실행 ────────────────────────────────────
    async def _with_keys(self, pool: KeyPool, run: Callable[[str], Awaitable[T]], what: str) -> T:
        """풀의 키를 하나씩 써 본다. 429 를 맞은 키는 쉬게 하고 다음 키로 넘어간다."""
        if not pool:
            raise GeminiError(f"{what}: Gemini 키가 설정되지 않았습니다")
        tried = 0
        shaky = 0                      # 일시적 과부하로 다시 시도한 횟수
        last: _Limit | None = None
        while True:
            key = await pool.pick()
            if key is None:
                wait = last.retry_after if last else COOLDOWN_PER_MINUTE
                raise GeminiError(
                    f"{what}: 키 {len(pool.keys)}개가 모두 한도에 걸렸습니다"
                    + (f" ({last.message})" if last else ""),
                    rate_limited=True, exhausted=True, retry_after=wait,
                )
            try:
                return await run(key)
            except _Transient as e:
                if shaky >= len(_BACKOFF):
                    raise GeminiError(f"{what}: 모델이 계속 붐빕니다 ({e.message})",
                                      retry_after=int(_BACKOFF[-1]), busy=True) from None
                await asyncio.sleep(_BACKOFF[shaky])
                shaky += 1
                log.info("gemini %s 일시 오류 — %d번째 재시도", what, shaky)
                continue               # 다음 키로 (pick 이 라운드로빈이라 자연히 바뀐다)
            except _RateLimited as e:
                last = e.limit
                await pool.rest(key, e.limit.retry_after, f"{what} {'일일' if e.limit.daily else '분당'} 한도")
                tried += 1
                if tried >= len(pool.keys):     # 한 바퀴 다 돌았으면 더 볼 키가 없다
                    raise GeminiError(
                        f"{what}: 키 {len(pool.keys)}개가 모두 한도에 걸렸습니다 ({e.limit.message})",
                        rate_limited=True, exhausted=True, retry_after=e.limit.retry_after,
                    ) from None

    # ── 임베딩 ──────────────────────────────────────────────
    async def embed(self, text: str, task: str = "RETRIEVAL_QUERY") -> list[float]:
        # 같은 문장은 같은 벡터 — Redis 에 7일 보관해 무료 키 쿼터를 아낀다
        ck = cache.key("emb", self.embed_model.rsplit("/", 1)[-1], self.dim, task, cache.digest(text))
        hit = await cache.get_json(ck)
        if hit is not None:
            return hit
        vec = await self._with_keys(self.answers, lambda k: self._embed_once(k, text, task), "임베딩")
        await cache.set_json(ck, vec, get_settings().cache_ttl_embed)
        return vec

    async def _embed_once(self, key: str, text: str, task: str) -> list[float]:
        r = await self._http.post(
            f"{_BASE}/{self.embed_model}:embedContent?key={key}",
            json={
                "model": self.embed_model,
                "content": {"parts": [{"text": text[:2000]}]},
                "taskType": task,
                "outputDimensionality": self.dim,
            },
        )
        data = r.json()
        if _is_429(r.status_code, data):
            raise _RateLimited(_read_limit(data))
        if _is_transient(r.status_code, data):
            raise _Transient(str((data.get("error") or {}).get("message", r.status_code))[:120])
        if "embedding" not in data:
            raise GeminiError(f"embed failed: {json.dumps(data, ensure_ascii=False)[:200]}")
        return data["embedding"]["values"]

    # ── 생성 (JSON 응답 강제) ────────────────────────────────
    def _gen_payload(self, system: str, user: str, schema: dict[str, Any] | None,
                     temperature: float) -> dict[str, Any]:
        cfg: dict[str, Any] = {
            "temperature": temperature,            # 근거 기반 답변 — 낮게 고정
            "responseMimeType": "application/json",
            "thinkingConfig": {"thinkingLevel": get_settings().gemini_thinking_level},   # 지연 시간 ↓
        }
        if schema:
            cfg["responseSchema"] = schema
        return {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": cfg,
        }

    async def generate_json(self, system: str, user: str, schema: dict[str, Any] | None = None,
                            temperature: float = 0.2, *, pool: KeyPool | None = None,
                            what: str = "답변 생성") -> dict[str, Any]:
        payload = self._gen_payload(system, user, schema, temperature)

        async def once(key: str) -> dict[str, Any]:
            r = await self._http.post(f"{_BASE}/{self.gen_model}:generateContent?key={key}", json=payload)
            data = r.json()
            if _is_429(r.status_code, data):
                raise _RateLimited(_read_limit(data))
            if _is_transient(r.status_code, data):
                raise _Transient(str((data.get("error") or {}).get("message", r.status_code))[:120])
            try:
                return _parse_json(data["candidates"][0]["content"]["parts"][0]["text"])
            except (KeyError, IndexError):
                raise GeminiError(f"generate failed: {json.dumps(data, ensure_ascii=False)[:300]}") from None

        return await self._with_keys(pool or self.answers, once, what)

    # ── 요약 (백그라운드, 전용 키) ────────────────────────────
    async def summarize_question(self, message: str, age_months: int | None) -> str | None:
        """부모 질문을 한 문장으로. DB 에는 원문 대신 이 요약만 남는다.
        실패하면 None — 사용자 응답과 무관한 백그라운드 작업이라 조용히 넘어간다."""
        from app.domains.chat import prompts

        try:
            out = await self.generate_json(
                prompts.SUMMARY_SYSTEM,
                prompts.build_summary_prompt(message, age_months),
                schema=prompts.SUMMARY_SCHEMA,
                temperature=0.0,
                pool=self.summaries,
                what="질문 요약",
            )
        except GeminiError as e:
            log.warning("질문 요약 건너뜀: %s", e)
            return None
        summary = str(out.get("summary") or "").strip()
        return summary[:80] or None

    async def snapshot(self) -> dict[str, object]:
        return {"answer": await self.answers.snapshot(), "summary": await self.summaries.snapshot()}


def _parse_json(text: str) -> dict[str, Any]:
    text = text.strip()
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise GeminiError("model did not return JSON")
    return json.loads(m.group(0))


_client: Gemini | None = None


def gemini() -> Gemini:
    global _client
    if _client is None:
        _client = Gemini()
    return _client


async def close_gemini() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


class _AnswerExtractor:
    """스트리밍 중인 JSON 텍스트에서 "answer" 문자열 값만 점진적으로 디코드해 새로 늘어난 부분을 돌려준다.
    grounded=false 가 먼저 보이면(범위 밖) 본문을 내보내지 않는다 — 최종 응답이 고정 문구로 바뀌므로."""
    _KEY = re.compile(r'"answer"\s*:\s*"')
    _NOT_GROUNDED = re.compile(r'"grounded"\s*:\s*false')

    def __init__(self) -> None:
        self.start: int | None = None
        self.emitted = ""
        self.closed = False

    def feed(self, buf: str) -> str:
        if self.closed or self._NOT_GROUNDED.search(buf):
            return ""
        if self.start is None:
            m = self._KEY.search(buf)
            if not m:
                return ""
            self.start = m.end()
        raw = buf[self.start:]
        end = None
        i = 0
        while i < len(raw):                      # 이스케이프되지 않은 첫 따옴표 = 값의 끝
            if raw[i] == "\\":
                i += 2
                continue
            if raw[i] == '"':
                end = i
                break
            i += 1
        if end is not None:
            raw, self.closed = raw[:end], True
        else:
            m = re.search(r"\\(u[0-9a-fA-F]{0,3})?$", raw)   # 잘린 이스케이프 꼬리는 다음 조각까지 보류
            if m:
                raw = raw[:m.start()]
        try:
            decoded = json.loads('"' + raw + '"')
        except json.JSONDecodeError:
            return ""
        if not decoded.startswith(self.emitted):
            return ""
        delta = decoded[len(self.emitted):]
        self.emitted = decoded
        return delta


async def generate_json_stream(system: str, user: str, schema: dict[str, Any] | None = None,
                               temperature: float = 0.2):
    """SSE 스트리밍. ("delta", 본문 조각) 을 흘려보내고 마지막에 ("final", 전체 JSON dict).

    한도는 스트림이 열리기 전(상태코드 429)에만 키를 바꿔 다시 시도한다.
    이미 글자를 내보낸 뒤라면 바꾸지 않는다 — 중간부터 다른 답이 이어지면 말이 안 맞는다.
    """
    g = gemini()
    payload = g._gen_payload(system, user, schema, temperature)
    pool = g.answers
    if not pool:
        raise GeminiError("답변 생성: Gemini 키가 설정되지 않았습니다")

    tried = 0
    shaky = 0
    last: _Limit | None = None
    while True:
        key = await pool.pick()
        if key is None:
            wait = last.retry_after if last else COOLDOWN_PER_MINUTE
            raise GeminiError(
                f"답변 생성: 키 {len(pool.keys)}개가 모두 한도에 걸렸습니다",
                rate_limited=True, exhausted=True, retry_after=wait,
            )

        buf, ext, started = "", _AnswerExtractor(), False
        async with g._http.stream(
            "POST", f"{_BASE}/{g.gen_model}:streamGenerateContent?alt=sse&key={key}", json=payload
        ) as r:
            if r.status_code != 200:
                body = await r.aread()
                try:
                    data = json.loads(body)
                except json.JSONDecodeError:
                    data = {"error": {"message": body[:200].decode(errors="ignore")}}
                if _is_429(r.status_code, data):
                    last = _read_limit(data)
                    await pool.rest(key, last.retry_after, f"스트리밍 {'일일' if last.daily else '분당'} 한도")
                    tried += 1
                    if tried >= len(pool.keys):
                        raise GeminiError(
                            f"답변 생성: 키 {len(pool.keys)}개가 모두 한도에 걸렸습니다 ({last.message})",
                            rate_limited=True, exhausted=True, retry_after=last.retry_after,
                        )
                    continue                      # 다음 키로 다시
                if _is_transient(r.status_code, data):
                    # 아직 한 글자도 안 보냈으니 다시 시도해도 화면이 어긋나지 않는다
                    if shaky >= len(_BACKOFF):
                        raise GeminiError("답변 생성: 모델이 계속 붐빕니다",
                                          retry_after=int(_BACKOFF[-1]), busy=True)
                    await asyncio.sleep(_BACKOFF[shaky])
                    shaky += 1
                    log.info("gemini 스트리밍 일시 오류 — %d번째 재시도", shaky)
                    continue
                raise GeminiError(f"generate failed: {json.dumps(data, ensure_ascii=False)[:300]}")

            async for line in r.aiter_lines():
                if not line.startswith("data:"):
                    continue
                try:
                    ev = json.loads(line[5:].strip())
                except json.JSONDecodeError:
                    continue
                if ev.get("error"):
                    raise GeminiError(f"generate failed: {json.dumps(ev['error'], ensure_ascii=False)[:300]}")
                try:
                    piece = ev["candidates"][0]["content"]["parts"][0]["text"]
                except (KeyError, IndexError):
                    continue
                buf += piece
                delta = ext.feed(buf)
                if delta:
                    started = True
                    yield ("delta", delta)

        if not buf and not started:
            raise GeminiError("generate failed: 빈 응답")
        yield ("final", _parse_json(buf))
        return
