"""채팅 파이프라인.
  ask:       의도 게이트 → 월령 추출 → 근거 검색(top_k 3, 연령 필터) → 근거 기반 생성 → 원문 없이 저장
  recommend: 답변의 치료영역 → 기관 매칭(정확도 순 3곳) → 사유 문장 → 저장
"""
import asyncio
import json
import re
from dataclasses import dataclass
from uuid import UUID

import asyncpg
from fastapi import HTTPException

from app.core import cache
from app.core.config import get_settings
from app.core.errors import ApiError, ErrorCode
from app.core.db import connection
from app.core.gemini import GeminiError, gemini, generate_json_stream
from app.domains.chat import prompts, repository as repo
from app.domains.chat.schemas import (AreaPriority, AskResponse, EvidenceListOut, RecommendedInstitution,
                                      RecommendResponse, SessionOut)
from app.domains.institution import repository as inst_repo
from app.domains.institution.service import to_card
from app.domains.knowledge import repository as kb_repo, service as kb_service
from app.domains.knowledge.service import to_evidence

VALID_CODES = {"SPEECH", "AUDIT", "ART", "MUSIC", "PLAY", "BEHAV", "PSYCH", "SENSORY", "MOTOR", "PSYMOTOR"}

# 진단 요구 게이트 — 유사도로는 못 거른다(측정: 0.77로 관련 문서 중앙값 수준). 규칙으로 앞에서 막는다.
_DIAG = re.compile(r"(진단|판정|확진|검사)\s*(해\s*주|해주|을\s*해|좀\s*해|내려|받아\s*볼)|(인지\s*아닌지|맞는지)\s*(진단|판정|알려)")
# 기관 추천 요청 — 아이 설명 없이 "추천해줘"만 오면 지역을 묻고(pick_region) 추천으로 보낸다
_RECO = re.compile(
    r"(기관|센터|치료실|병원|곳|데)\s*(을|를|좀|도)?\s*(추천|찾아|알려|소개)"   # "기관 추천해줘", "센터 찾아줘"
    r"|^\s*((네|응|예|좋아요?|그래)[,.!\s]*)?(추천\s*)?(해\s*줘|해\s*주세요|부탁\s*(해요?|드려요?|합니다)?)?\s*[!.~]*$"   # "네, 추천해주세요" / "추천해줘" / "네"
)
_AGE_Y = re.compile(r"(\d{1,2})\s*(살|세)")
_AGE_M = re.compile(r"(\d{1,3})\s*개월")


def _age_from(message: str) -> int | None:
    m = _AGE_M.search(message)
    if m:
        return int(m.group(1))
    y = _AGE_Y.search(message)
    if y:
        return int(y.group(1)) * 12          # "6살" → 72개월 (만 나이 가정)
    return None


# ── 세션 ──
async def create_session(conn, region_id, age) -> SessionOut:
    r = await repo.create_session(conn, region_id, age, get_settings().session_ttl_hours)
    s = await repo.get_session(conn, r["session_id"])
    return SessionOut(**dict(s))


async def get_session(conn, session_id: UUID) -> SessionOut:
    s = await repo.get_session(conn, session_id)
    if s is None:
        raise ApiError(404, ErrorCode.SESSION_NOT_FOUND, "세션이 없거나 만료되었습니다")
    return SessionOut(**dict(s))


# ── 질문 → 답변 ──
@dataclass
class _Ctx:
    s: asyncpg.Record
    names: dict[str, str]
    age: int | None
    evidence: list
    user_prompt: str


def _llm_error(e: GeminiError) -> ApiError:
    if e.rate_limited:
        return ApiError(503, ErrorCode.LLM_RATE_LIMITED, "지금 질문이 몰려 있어요. 몇 초 뒤 다시 시도해주세요",
                        {"retry_after_sec": 5})
    return ApiError(502, ErrorCode.LLM_FAILED, "답변 생성에 실패했어요. 잠시 후 다시 시도해주세요", {"cause": str(e)[:300]})


async def _prepare(conn: asyncpg.Connection, session_id: UUID, message: str) -> tuple[AskResponse | None, _Ctx | None]:
    """게이트·라우팅·검색까지. 생성이 필요 없으면 즉시 응답을 돌려준다 (ask / ask_stream 공용)."""
    s = await repo.get_session(conn, session_id)
    if s is None:
        raise ApiError(404, ErrorCode.SESSION_NOT_FOUND, "세션이 없거나 만료되었습니다")
    if not message.strip():
        raise ApiError(400, ErrorCode.MESSAGE_EMPTY, "질문을 입력해주세요")
    cfg = get_settings()
    names = await kb_repo.area_names(conn)
    age = s["child_age_months"] or _age_from(message)

    # tier 3-a: 진단 요구는 검색 전에 차단
    if _DIAG.search(message):
        aid = await repo.insert_answer(conn, session_id=session_id, areas=[], keywords=["진단요구"],
                                       tier=3, top_k=0, model="rule")
        return AskResponse(answer_id=aid, intent="diagnosis", text=prompts.TIER3_DIAGNOSIS, highlights=[],
                           areas=[], evidence_count=0, fallback_tier=3, can_recommend=False,
                           ask_region=False, recommend_for=None,
                           next_prompts=["아이가 말이 느린 것 같아요", "또래와 어울리는 걸 어려워해요"]), None

    # 추천 요청: 검색·생성 없이 라우팅만. 근거 답변이 있어야 하고, 지역이 없으면 먼저 묻는다
    if _RECO.search(message.strip()):
        last = await repo.latest_grounded_answer(conn, session_id)
        if last is None:
            return AskResponse(answer_id=None, intent="need_context", highlights=[], areas=[], evidence_count=0,
                               fallback_tier=0, can_recommend=False, ask_region=False, recommend_for=None,
                               text="먼저 아이의 걱정되는 모습을 알려주시면, 맞는 치료영역을 찾은 뒤 기관을 추천해드릴게요.",
                               next_prompts=["아이가 말이 느린 것 같아요", "이름을 불러도 잘 쳐다보지 않아요"]), None
        if s["region_id"] is None:
            return AskResponse(answer_id=None, intent="pick_region", highlights=[], areas=[], evidence_count=0,
                               fallback_tier=0, can_recommend=True, ask_region=True, recommend_for=last["answer_id"],
                               text="어느 지역에서 찾아드릴까요? 시·도와 시·군·구를 골라주세요.", next_prompts=[]), None
        return AskResponse(answer_id=None, intent="recommend", highlights=[], areas=[], evidence_count=0,
                           fallback_tier=0, can_recommend=True, ask_region=False, recommend_for=last["answer_id"],
                           text=f"{s['sido']} 기관을 찾아볼게요.", next_prompts=[]), None

    evidence = await kb_service.retrieve(conn, message, age_months=age, top_k=cfg.top_k)
    return None, _Ctx(s=s, names=names, age=age, evidence=evidence,
                      user_prompt=prompts.build_user_prompt(message, age, evidence))


async def _finalize(conn: asyncpg.Connection, session_id: UUID, ctx: _Ctx, out: dict) -> AskResponse:
    """모델 JSON → tier 판정·볼드·저장·응답 (ask / ask_stream 공용)."""
    cfg, names, s, evidence, age = get_settings(), ctx.names, ctx.s, ctx.evidence, ctx.age
    grounded = bool(out.get("grounded"))
    areas = [a for a in out.get("areas", []) if a.get("area_code") in VALID_CODES]
    areas.sort(key=lambda a: a.get("priority", 3))
    keywords = [k.strip()[:20] for k in out.get("keywords", []) if k and k.strip()][:4]
    summary = (out.get("question_summary") or "").strip()[:80] or None   # 원문 대신 저장하는 요약

    if not grounded:                       # tier 3-b: 범위 밖
        tier, text, areas, highlights = 3, prompts.TIER3_OUT_OF_SCOPE, [], []
    else:
        tier = 1 if areas else 2           # tier 2: 근거는 있으나 영역 미도출
        area_names = [names.get(a["area_code"], a["area_code"]) for a in areas]
        text, highlights = _bold(out.get("answer", ""), area_names + keywords)   # 모델이 굵힌 것 + 서버 보강
        if tier == 1:
            text += "\n\n이 영역을 다루는 기관을 추천해드릴까요?"

    aid = await repo.insert_answer(conn, session_id=session_id, areas=areas, keywords=keywords,
                                   tier=tier, top_k=cfg.top_k, model=cfg.gemini_gen_model,
                                   question_summary=summary)
    if tier < 3:
        await repo.insert_evidence(conn, aid, [(e.chunk_id, i, e.similarity) for i, e in enumerate(evidence, 1)])
        # 답변 본문은 DB에 두지 않는다. 👍👎가 눌리면 학습 표본으로 옮길 수 있게 세션 TTL 동안만 Redis 보관
        await cache.set_json(cache.key("conv", aid), {"answer": text, "age": age},
                             cfg.session_ttl_hours * 3600)

    return AskResponse(
        answer_id=aid, intent=("answer" if tier < 3 else "out_of_scope"), text=text, highlights=highlights,
        areas=[AreaPriority(area_code=a["area_code"], area_name=names.get(a["area_code"], a["area_code"]),
                            priority=min(3, max(1, int(a.get("priority", 3))))) for a in areas],
        evidence_count=len(evidence) if tier < 3 else 0,
        fallback_tier=tier, can_recommend=(tier == 1),
        ask_region=(tier == 1 and s["region_id"] is None),
        recommend_for=(aid if tier == 1 else None),
        next_prompts=(["네, 추천해주세요", "더 물어볼게요"] if tier == 1 else ["더 물어볼게요"]),
    )


async def ask(conn: asyncpg.Connection, session_id: UUID, message: str) -> AskResponse:
    short, ctx = await _prepare(conn, session_id, message)
    if short is not None:
        return short
    assert ctx is not None
    try:
        out = await gemini().generate_json(prompts.SYSTEM, ctx.user_prompt, schema=prompts.RESPONSE_SCHEMA)
    except GeminiError as e:
        raise _llm_error(e)
    return await _finalize(conn, session_id, ctx, out)


def _sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def ask_stream(session_id: UUID, message: str):
    """SSE: meta → delta* → done  |  error.  본문 조각(delta)은 모델 원문, done 의 text 가 볼드·마무리 문장까지 반영된 최종본."""
    async with connection() as conn:                # 스트리밍 동안 커넥션을 직접 쥔다 (Depends 수명 문제 회피)
        try:
            short, ctx = await _prepare(conn, session_id, message)
        except ApiError as e:
            yield _sse("error", {"code": e.code.value, "message": e.message, "details": e.details})
            return
        if short is not None:
            yield _sse("done", short.model_dump(mode="json"))
            return
        assert ctx is not None
        yield _sse("meta", {"evidence_count": len(ctx.evidence)})

        out: dict | None = None
        emitted = False
        for attempt in range(2):                    # 429 는 아직 아무것도 못 보냈을 때만 4초 뒤 1회 재시도
            try:
                async for kind, val in generate_json_stream(prompts.SYSTEM, ctx.user_prompt, schema=prompts.RESPONSE_SCHEMA):
                    if kind == "delta":
                        emitted = True
                        yield _sse("delta", {"text": val})
                    else:
                        out = val
                break
            except GeminiError as e:
                if e.rate_limited and attempt == 0 and not emitted:
                    await asyncio.sleep(4)
                    continue
                err = _llm_error(e)
                yield _sse("error", {"code": err.code.value, "message": err.message, "details": err.details})
                return
        if out is None:
            yield _sse("error", {"code": ErrorCode.LLM_FAILED.value, "message": "답변 생성에 실패했어요. 잠시 후 다시 시도해주세요"})
            return
        res = await _finalize(conn, session_id, ctx, out)
        yield _sse("done", res.model_dump(mode="json"))


def _bold(text: str, terms: list[str]) -> tuple[str, list[str]]:
    """치료영역명·키워드가 본문에 나오면 **굵게**. 이미 굵은 구간은 건드리지 않는다."""
    already = re.findall(r"\*\*(.+?)\*\*", text)              # 모델이 프롬프트 규칙대로 굵힌 구간
    for t in sorted({t for t in terms if t and len(t) >= 2}, key=len, reverse=True):
        if any(t in a for a in already):
            continue
        pat = re.compile(r"(?<!\*)" + re.escape(t) + r"(?!\*)")
        if pat.search(text):
            text = pat.sub(f"**{t}**", text, count=1)
    hits = list(dict.fromkeys(re.findall(r"\*\*(.+?)\*\*", text)))
    return text, hits


async def evidence(conn, answer_id: UUID) -> EvidenceListOut:
    if await repo.get_answer(conn, answer_id) is None:
        raise ApiError(404, ErrorCode.ANSWER_NOT_FOUND, "답변을 찾을 수 없습니다")
    rows = await repo.list_evidence(conn, answer_id)
    return EvidenceListOut(answer_id=answer_id, items=[to_evidence(r) for r in rows])


# ── 추천 ──
def _reason(card, want: list[str], names: dict[str, str]) -> str:
    """구조화 데이터만으로 쓰는 사유 문장 — LLM 없이 결정적. 환각 없음."""
    hit = [c for c in want if c in card.area_codes]
    hit_names = "·".join(names.get(c, c) for c in hit)
    n_all = len(want)
    if len(hit) == n_all and n_all > 1:
        head = f"필요한 {n_all}가지 영역({hit_names})을 한 곳에서 모두 받을 수 있어요."
    elif len(hit) > 1:
        head = f"{hit_names} {len(hit)}가지를 함께 다룹니다."
    else:
        head = f"{hit_names}을 제공합니다."
    price = card.price_label
    tail = f" 공시 단가는 {price.replace('회기당 ', '')}이에요." if price else ""
    visit = " 방문 서비스도 가능합니다." if card.visit_available else ""
    return head + tail + visit


async def recommend(conn: asyncpg.Connection, *, session_id: UUID, answer_id: UUID,
                    region_id: int | None, sido: str | None, max_price: int | None) -> RecommendResponse:
    s = await repo.get_session(conn, session_id)
    a = await repo.get_answer(conn, answer_id)
    if s is None:
        raise ApiError(404, ErrorCode.SESSION_NOT_FOUND, "세션이 없거나 만료되었습니다")
    if a is None:
        raise ApiError(404, ErrorCode.ANSWER_NOT_FOUND, "답변을 찾을 수 없습니다")
    if a["session_id"] != session_id:
        raise ApiError(409, ErrorCode.ANSWER_SESSION_MISMATCH, "이 세션의 답변이 아닙니다")
    if a["fallback_tier"] != 1:
        raise ApiError(409, ErrorCode.ANSWER_NOT_GROUNDED, "근거가 확보된 답변에서만 추천할 수 있습니다")

    import json
    areas = json.loads(a["extracted_areas"]) if isinstance(a["extracted_areas"], str) else a["extracted_areas"]
    want = [x["area_code"] for x in sorted(areas, key=lambda x: x.get("priority", 3))]
    names = await kb_repo.area_names(conn)

    # 지역은 추천 시점에 받는다: region_id(시·군·구) > sido(시·도) > 세션에 이미 있는 지역 > 전국
    if region_id is not None:
        picked = await repo.set_session_region(conn, session_id, region_id)
        if picked is None:
            raise ApiError(404, ErrorCode.REGION_NOT_FOUND, "지역을 찾을 수 없습니다")
        scope = picked
    elif sido:
        scope = sido
        if s["region_id"] is None:
            await repo.set_session_sido(conn, session_id, sido)
    else:
        scope = s["sido"]

    # 전 영역 조합 → 상위 2개 → 1순위 순으로 완화하며 3곳 확보
    rows: list = []
    for k in range(len(want), 0, -1):
        rows = await inst_repo.recommend(conn, area_codes=want[:k], sido=scope, max_price=max_price, limit=3)
        if len(rows) >= 3 or k == 1:
            break

    items: list[RecommendedInstitution] = []
    for rank, r in enumerate(rows, 1):
        card = to_card(r)
        items.append(RecommendedInstitution(**card.model_dump(), rank=rank, reason=_reason(card, want, names)))
    await repo.insert_recommendations(conn, answer_id, [(i.biz_no, i.rank, i.reason) for i in items])

    want_names = "·".join(names.get(c, c) for c in want[:2])
    where = f"{scope} " if scope else "전국 "
    intro = (f"{where}기관 중 {want_names}을(를) 함께 볼 수 있는 곳 {len(items)}곳을 찾았어요."
             if items else f"{where}기관 중 조건에 맞는 곳을 찾지 못했어요.")
    return RecommendResponse(
        answer_id=answer_id, intro=intro, items=items, scope_sido=scope,
        browse_hint="다른 지역이나 더 많은 기관은 둘러보기에서 지역을 바꿔 확인할 수 있어요.",
    )


# ── 추천 칩 회전 ───────────────────────────────────────────
async def rotating_prompts(conn: asyncpg.Connection) -> list[dict]:
    """활성 칩 전체(10분 캐시)에서 호출마다 다른 N개.
    Redis 있으면 라운드로빈(연속 호출이 항상 다른 묶음) · 없으면 무작위."""
    import random
    n_take = get_settings().prompt_count
    allp = await cache.cached(cache.key("prompts", "all", "v2"), get_settings().cache_ttl_read,
                              lambda: _fetch_prompts(conn))
    if len(allp) <= n_take:
        return allp
    off = await cache.next_offset(cache.key("prompts", "rr"))
    if off is None:
        return random.sample(allp, n_take)
    start = (off * n_take) % len(allp)
    return [allp[(start + i) % len(allp)] for i in range(n_take)]


async def _fetch_prompts(conn: asyncpg.Connection) -> list[dict]:
    return [dict(r) for r in await repo.list_prompts(conn)]
