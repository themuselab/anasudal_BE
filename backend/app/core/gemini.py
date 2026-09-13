"""Gemini REST 클라이언트 — 임베딩(검색용)과 생성(답변용) 두 역할.
SDK 대신 httpx로 직접 호출: 의존성이 가볍고 응답 스키마가 명시적이다.
"""
import asyncio
import json
import re
from typing import Any

import httpx

from app.core import cache
from app.core.config import get_settings

_BASE = "https://generativelanguage.googleapis.com/v1beta"


class GeminiError(RuntimeError):
    def __init__(self, msg: str, rate_limited: bool = False):
        super().__init__(msg)
        self.rate_limited = rate_limited     # 429: 무료 키 분당 한도 → 503 LLM_RATE_LIMITED 로 구분


class Gemini:
    def __init__(self) -> None:
        s = get_settings()
        self.key = s.gemini_api_key
        self.embed_model = s.gemini_embed_model
        self.gen_model = s.gemini_gen_model
        self.dim = s.embed_dim
        self._http = httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0))

    async def aclose(self) -> None:
        await self._http.aclose()

    # ── 임베딩 ──────────────────────────────────────────────
    async def embed(self, text: str, task: str = "RETRIEVAL_QUERY") -> list[float]:
        # 같은 문장은 같은 벡터 — Redis에 7일 보관해 무료 키 쿼터를 아낀다
        ck = cache.key("emb", self.embed_model.rsplit("/", 1)[-1], self.dim, task, cache.digest(text))
        hit = await cache.get_json(ck)
        if hit is not None:
            return hit
        vec = await self._embed_remote(text, task)
        await cache.set_json(ck, vec, get_settings().cache_ttl_embed)
        return vec

    async def _embed_remote(self, text: str, task: str) -> list[float]:
        url = f"{_BASE}/{self.embed_model}:embedContent?key={self.key}"
        payload = {
            "model": self.embed_model,
            "content": {"parts": [{"text": text[:2000]}]},
            "taskType": task,
            "outputDimensionality": self.dim,
        }
        r = await self._http.post(url, json=payload)
        data = r.json()
        if "embedding" not in data:
            raise GeminiError(f"embed failed: {json.dumps(data, ensure_ascii=False)[:200]}")
        return data["embedding"]["values"]

    # ── 생성 (JSON 응답 강제) ────────────────────────────────
    async def generate_json(self, system: str, user: str, schema: dict[str, Any] | None = None,
                            temperature: float = 0.2) -> dict[str, Any]:
        url = f"{_BASE}/{self.gen_model}:generateContent?key={self.key}"
        gen_cfg: dict[str, Any] = {
            "temperature": temperature,            # 근거 기반 답변 — 낮게 고정
            "responseMimeType": "application/json",
            "thinkingConfig": {"thinkingLevel": get_settings().gemini_thinking_level},   # 지연 시간 ↓
        }
        if schema:
            gen_cfg["responseSchema"] = schema
        payload = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": gen_cfg,
        }
        last: GeminiError | None = None
        for attempt in range(2):                    # 일시적 오류(429·빈 후보·비JSON)는 1회 재시도
            r = await self._http.post(url, json=payload)
            data = r.json()
            if r.status_code == 429 or (data.get("error") or {}).get("code") == 429:
                last = GeminiError("rate limited: " + str((data.get("error") or {}).get("message", ""))[:200], rate_limited=True)
                if attempt == 0:
                    await asyncio.sleep(4)          # 분당 한도는 몇 초 뒤 풀리는 경우가 많다
                continue
            try:
                text = data["candidates"][0]["content"]["parts"][0]["text"]
                return _parse_json(text)
            except (KeyError, IndexError):
                last = GeminiError(f"generate failed: {json.dumps(data, ensure_ascii=False)[:300]}")
            except (GeminiError, json.JSONDecodeError) as e:
                last = e if isinstance(e, GeminiError) else GeminiError(str(e))
        assert last is not None
        raise last


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
    """SSE 스트리밍. ("delta", 본문 조각) 을 흘려보내고 마지막에 ("final", 전체 JSON dict)."""
    g = gemini()
    url = f"{_BASE}/{g.gen_model}:streamGenerateContent?alt=sse&key={g.key}"
    gen_cfg: dict[str, Any] = {"temperature": temperature, "responseMimeType": "application/json",
                               "thinkingConfig": {"thinkingLevel": get_settings().gemini_thinking_level}}
    if schema:
        gen_cfg["responseSchema"] = schema
    payload = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": gen_cfg,
    }
    buf, ext = "", _AnswerExtractor()
    async with g._http.stream("POST", url, json=payload) as r:
        if r.status_code != 200:
            body = await r.aread()
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                data = {"error": {"message": body[:200].decode(errors="ignore")}}
            if r.status_code == 429:
                raise GeminiError("rate limited: " + str((data.get("error") or {}).get("message", ""))[:200], rate_limited=True)
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
                yield ("delta", delta)
    yield ("final", _parse_json(buf))
