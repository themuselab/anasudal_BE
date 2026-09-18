"""채팅 파이프라인.
  ask:       의도 게이트 → 월령 추출 → 근거 검색(top_k 4, 연령 필터) → 근거 기반 생성 → 원문 없이 저장
  recommend: 답변의 치료영역 → 기관 매칭(정확도 순 3곳) → 사유 문장 → 저장
"""
import asyncio
import json
import logging
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
from app.domains.chat import prompts, regions, repository as repo, summarize
from app.domains.chat.schemas import (AreaPriority, AskResponse, EvidenceListOut, RecommendedInstitution,
                                      RecommendResponse, SessionOut)
from app.domains.institution import repository as inst_repo
from app.domains.institution.service import to_card
from app.domains.knowledge import repository as kb_repo, service as kb_service
from app.domains.knowledge.service import to_evidence

log = logging.getLogger("anasudal.chat")

VALID_CODES = {"SPEECH", "AUDIT", "ART", "MUSIC", "PLAY", "BEHAV", "PSYCH", "SENSORY", "MOTOR", "PSYMOTOR"}

# 진단 요구 게이트 — 유사도로는 못 거른다(측정: 0.77로 관련 문서 중앙값 수준). 규칙으로 앞에서 막는다.
_DIAG = re.compile(r"(진단|판정|확진|검사)\s*(해\s*주|해주|을\s*해|좀\s*해|내려|받아\s*볼)|(인지\s*아닌지|맞는지)\s*(진단|판정|알려)")
# 기관 추천 요청 — 아이 설명 없이 "추천해줘"만 오면 지역을 묻고(pick_region) 추천으로 보낸다
_RECO = re.compile(
    r"(기관|센터|치료실|병원|곳|데)\s*(을|를|좀|도)?\s*(추천|찾아|알려|소개)"   # "기관 추천해줘", "센터 찾아줘"
    r"|^\s*((네|응|예|좋아요?|그래)[,.!\s]*)?(추천\s*)?(해\s*줘|해\s*주세요|부탁\s*(해요?|드려요?|합니다)?)?\s*[!.~]*$"   # "네, 추천해주세요" / "추천해줘" / "네"
)
# "같이 살펴볼까요?" 칩. 문구가 아니라 동작이라 코드에 둔다 (_RECO 와 같은 이유)
SCREEN_PROMPT = "아이 반응을 같이 살펴볼까요?"          # 답변 뒤 칩
SCREEN_HOME_PROMPT = "우리 아이, 잘 자라고 있는 걸까요?"   # 첫 화면 고정 칩
# 문장 전체가 이 칩일 때만 잡는다. 긴 질문에 이 말이 섞여 있으면 진짜 질문이므로
# 검색·답변 경로로 보내야 한다.
_SCREEN = re.compile(
    r"^\s*(?:아이\s*반응을?\s*같이\s*살펴|우리\s*아이[,\s]*잘\s*자라고\s*있)[^.?!]{0,12}[?!.~]*\s*$")
# 근거 논문이 다룬 연령. 이 밖에는 과제 자체가 검증되지 않았다
SCREEN_AGE_LO, SCREEN_AGE_HI = 18, 48
# 월령을 물을 때 같이 주는 빠른 답. 과제 세트가 갈리는 지점(18·24·36)을 걸치도록 골랐다.
# 정확한 개월을 아는 부모는 그냥 입력하면 된다.
AGE_CHIPS = ["18개월", "24개월", "30개월", "36개월", "42개월"]

# 가벼운 인사·서비스 문의 — 검색·생성 없이 무엇을 해주는 곳인지 알려준다
_GREETING = re.compile(
    r"^\s*(?:"
    r"안녕(하세요|하십니까|히\s*계세요)?|하이|하잉|헬로|hello|hi|hey|ㅎㅇ|ㅎㅐㅇ|반가워(요)?|"
    r"(넌|너|여긴|여기(는)?|이거|이곳(은)?)?\s*(뭐|무엇|누구|어떤\s*(서비스|곳|앱))(야|니|예요|에요|인가요|하는\s*(곳|거)(야|예요|에요)?)?|"
    r"뭐\s*(하는|해주는)\s*(서비스|곳|거)(야|니|예요|에요|인가요)?|"
    r"어떻게\s*(쓰는|사용하는)\s*거(야|예요|에요)?|"
    r"뭘\s*(할\s*수\s*있|도와줄\s*수\s*있)(어|나요|어요)?"
    r")\s*[?!.~]*\s*$",
    re.IGNORECASE,
)
_AGE_Y = re.compile(r"(\d{1,2})\s*(살|세)")
_AGE_M = re.compile(r"(\d{1,3})\s*개월")

# 추천 요청 문구를 걷어낸 뒤 아이 이야기가 남는지 보려고 쓴다.
# "36개월인데 말이 느려요. 언어치료 기관 추천해주세요" 는 추천 요청이자 상담이다.
# 이걸 추천 분기로만 보내면 방금 적은 걸 또 적으라고 되묻게 된다 (실측된 되묻기 문제).
_RECO_PHRASE = re.compile(
    r"(기관|센터|치료실|병원|곳|데)\s*(을|를|좀|도)?\s*(추천|찾아|알려|소개)\s*(해\s*)?(줘|주세요|주실래요|드려요)?"
    r"|(네|응|예|좋아요?|그래)[,.!\s]*"
    r"|(추천|부탁)\s*(해\s*)?(줘|주세요|드려요|합니다)?"
    r"|근처|주변|가까운|우리\s*동네"
)
_FILLER = re.compile(r"[\s,.!?~·]|(좀|혹시|그럼|그러면|이제|저기|안녕하세요|안녕)")


def _has_own_context(message: str) -> bool:
    """추천 요청 말고 아이에 대한 이야기가 함께 들어 있는가."""
    if _age_from(message) is not None:
        return True
    rest = _FILLER.sub("", _RECO_PHRASE.sub("", message))
    return len(rest) >= 8


def _age_from(message: str) -> int | None:
    """문장에서 월령을 읽는다. "2살 6개월" 처럼 둘이 같이 오면 합친다."""
    y = _AGE_Y.search(message)
    m = _AGE_M.search(message)
    if y and m:                              # "2살 6개월" → 30
        return int(y.group(1)) * 12 + int(m.group(1))
    if m:
        return int(m.group(1))
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
    message: str            # 요약 작업에만 넘긴다. DB 에는 요약 결과만 남는다


def _llm_error(e: GeminiError) -> ApiError:
    if e.exhausted:
        return ApiError(503, ErrorCode.LLM_RATE_LIMITED,
                        "지금은 답변을 만들 수 없어요. 잠시 후 다시 시도해주세요",
                        {"retry_after_sec": max(5, min(e.retry_after, 300))})
    if e.rate_limited or e.busy:
        # busy = 모델 과부하(503). 재시도까지 다 해보고도 안 되면 여기로 온다.
        # 우리 쪽 장애가 아니라 곧 풀리는 상황이라 원인 문자열을 사용자에게 보이지 않는다.
        return ApiError(503, ErrorCode.LLM_RATE_LIMITED, "지금 질문이 몰려 있어요. 몇 초 뒤 다시 시도해주세요",
                        {"retry_after_sec": max(5, e.retry_after or 5)})
    return ApiError(502, ErrorCode.LLM_FAILED, "답변 생성에 실패했어요. 잠시 후 다시 시도해주세요", {"cause": str(e)[:300]})


def _screen_age(age: int | None) -> int | None:
    """관찰 과제를 이어서 할 수 있는 월령인지. 아니면 None 이라 화면이 칩을 안 띄운다.

    자폐를 언급한 질문에만 띄우지 않는다 — "자폐 얘기를 꺼냈더니 검사를 권하더라"는
    사실상 라벨이고, 진단하지 않는다는 원칙과도 부딪힌다. 근거 있는 답변이 나온
    18~48개월이면 무엇을 물었든 똑같이 제안한다.
    """
    return age if age is not None and SCREEN_AGE_LO <= age <= SCREEN_AGE_HI else None


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
    # 문장에서 찾은 월령은 세션에 남긴다. 안 남기면 다음 메시지부터 나이를 잊어버려서
    # 검색의 연령 필터가 안 먹고, "같이 살펴볼까요?" 칩을 눌러도 월령이 없어 되돌아간다.
    if age is not None and s["child_age_months"] is None:
        await repo.patch_session(conn, session_id, region_id=None, age=age)

    # 인사·서비스 문의: 검색도 생성도 하지 않고 무엇을 해주는 곳인지 소개한다
    if _GREETING.match(message):
        return AskResponse(answer_id=None, intent="need_context", text=prompts.GREETING, highlights=[],
                           areas=[], evidence_count=0, fallback_tier=0, can_recommend=False,
                           ask_region=False, recommend_for=None,
                           next_prompts=await followup_prompts(conn)), None

    # tier 3-a: 진단 요구는 검색 전에 차단
    if _DIAG.search(message):
        aid = await repo.insert_answer(conn, session_id=session_id, areas=[], keywords=["진단요구"],
                                       tier=3, top_k=0, model="rule")
        return AskResponse(answer_id=aid, intent="diagnosis", text=prompts.TIER3_DIAGNOSIS, highlights=[],
                           areas=[], evidence_count=0, fallback_tier=3, can_recommend=False,
                           ask_region=False, recommend_for=None,
                           next_prompts=await followup_prompts(conn)), None

    # 문장에 지역이 적혀 있으면 지금 잡아둔다 — 나중에 또 묻지 않으려고.
    # ("분당 근처 언어치료 기관 추천해주세요" 에 대고 시·도부터 고르라고 하면 안 된다)
    region_id = s["region_id"]
    if region_id is None:
        found = await regions.find_region(conn, message)
        if found is not None:
            await repo.set_session_region(conn, session_id, found["region_id"])
            region_id = found["region_id"]
            s = await repo.get_session(conn, session_id) or s

    # 관찰 시작: 검색·생성 없이 화면만 바꾼다
    if _SCREEN.search(message) and (age is None or SCREEN_AGE_LO <= age <= SCREEN_AGE_HI):
        if age is None:
            # 월령을 모르면 먼저 묻는다. 카드로 띄우지 않고 대화로 묻는다 —
            # 부모는 그냥 "30개월이요" 라고 답하면 되고, 칩은 빠른 길일 뿐이다.
            return AskResponse(
                answer_id=None, intent="screening", highlights=[], areas=[], evidence_count=0,
                fallback_tier=0, can_recommend=False, ask_region=False, recommend_for=None,
                text=("같이 살펴볼게요. 먼저 **아이가 몇 개월인가요?**\n\n"
                      "월령에 따라 해볼 것이 달라져서요. 개월 수로 알려주시거나 아래에서 골라주세요."),
                next_prompts=AGE_CHIPS, screen_age_months=None), None
        return AskResponse(
            answer_id=None, intent="screening", highlights=[], areas=[], evidence_count=0,
            fallback_tier=0, can_recommend=False, ask_region=False, recommend_for=None,
            text="아이와 함께 몇 가지를 해보면서 어떤 모습이 보이는지 적어볼게요. "
                 "진단이 아니라 참고용 기록이에요.",
            next_prompts=[], screen_age_months=age), None

    # 추천 요청: 검색·생성 없이 라우팅만. 근거 답변이 있어야 하고, 지역이 없으면 먼저 묻는다.
    # 단, 아이 이야기가 함께 담긴 첫 문장은 추천 분기로 보내지 않는다 — 먼저 답을 하고
    # 추천 칩을 띄운다. 그래야 "이미 말했는데 또 물어본다"가 생기지 않는다.
    if _RECO.search(message.strip()):
        last = await repo.latest_grounded_answer(conn, session_id)
        if last is None and not _has_own_context(message):
            return AskResponse(answer_id=None, intent="need_context", highlights=[], areas=[], evidence_count=0,
                               fallback_tier=0, can_recommend=False, ask_region=False, recommend_for=None,
                               text="먼저 아이의 걱정되는 모습을 알려주시면, 맞는 치료영역을 찾은 뒤 기관을 추천해드릴게요.",
                               next_prompts=await followup_prompts(conn)), None
        if last is not None:
            if region_id is None:
                return AskResponse(answer_id=None, intent="pick_region", highlights=[], areas=[], evidence_count=0,
                                   fallback_tier=0, can_recommend=True, ask_region=True,
                                   recommend_for=last["answer_id"],
                                   text="어느 지역에서 찾아드릴까요? 시·도와 시·군·구를 골라주세요.", next_prompts=[]), None
            return AskResponse(answer_id=None, intent="recommend", highlights=[], areas=[], evidence_count=0,
                               fallback_tier=0, can_recommend=True, ask_region=False,
                               recommend_for=last["answer_id"],
                               text=f"{s['sido']} {s['sigungu']} 기관을 찾아볼게요.", next_prompts=[]), None
        # 근거 답변이 아직 없지만 아이 이야기가 있다 → 아래 일반 경로(검색 → 답변)로 내려간다

    try:
        evidence = await kb_service.retrieve(conn, message, age_months=age, top_k=cfg.top_k)
    except GeminiError as e:
        # 임베딩도 답변 키 풀을 쓴다. 키가 다 막히면 검색 자체가 안 되므로 여기서 끝낸다
        # (같은 문장을 전에 물었다면 임베딩 캐시가 있어 여기까지 오지 않는다)
        raise _llm_error(e)
    return None, _Ctx(s=s, names=names, age=age, evidence=evidence, message=message,
                      user_prompt=prompts.build_user_prompt(message, age, evidence))


async def _finalize(conn: asyncpg.Connection, session_id: UUID, ctx: _Ctx, out: dict) -> AskResponse:
    """모델 JSON → tier 판정·볼드·저장·응답 (ask / ask_stream 공용)."""
    cfg, names, s, evidence, age = get_settings(), ctx.names, ctx.s, ctx.evidence, ctx.age
    grounded = bool(out.get("grounded"))
    areas = [a for a in out.get("areas", []) if a.get("area_code") in VALID_CODES]
    areas.sort(key=lambda a: a.get("priority", 3))
    keywords = [k.strip()[:20] for k in out.get("keywords", []) if k and k.strip()][:4]

    if not grounded:                       # tier 3-b: 범위 밖
        tier, text, areas, highlights = 3, prompts.TIER3_OUT_OF_SCOPE, [], []
    else:
        tier = 1 if areas else 2           # tier 2: 근거는 있으나 영역 미도출
        area_names = [names.get(a["area_code"], a["area_code"]) for a in areas]
        text, highlights = _bold(out.get("answer", ""), area_names + keywords)   # 모델이 굵힌 것 + 서버 보강
        if tier == 1:
            text += "\n\n이 영역을 다루는 기관을 추천해드릴까요?"

    aid = await repo.insert_answer(conn, session_id=session_id, areas=areas, keywords=keywords,
                                   tier=tier, top_k=cfg.top_k, model=cfg.gemini_gen_model)
    # 질문 요약은 전용 키로 응답 뒤에 따로 만든다 (답변 쿼터·속도와 분리)
    summarize.schedule(aid, ctx.message, age)
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
        # tier 1 은 치료영역이 잡혔으니 기관 추천으로, 그 밖에는 상담을 시작할 문장을 준다.
        # 절차·제도 질문(tier 2)은 답을 듣고 나면 "그래서 우리 애는?" 이 남는데
        # 아무것도 안 주면 대화가 거기서 끊긴다.
        # "네, 추천해주세요" 만 코드에 둔다 — 문구가 아니라 동작이라 _RECO 정규식과 짝이다.
        next_prompts=(_tier1_prompts(age) if tier == 1 else await followup_prompts(conn)),
        screen_age_months=_screen_age(age) if tier < 3 else None,
    )


def _tier1_prompts(age: int | None) -> list[str]:
    chips = ["네, 추천해주세요"]
    if _screen_age(age) is not None:
        chips.append(SCREEN_PROMPT)
    return chips


async def _degraded(conn: asyncpg.Connection, session_id: UUID, ctx: _Ctx) -> AskResponse:
    """Gemini 키가 모두 한도에 걸렸을 때의 대체 답변.

    문장은 못 쓰지만 검색은 됐으므로, 찾은 근거를 그대로 보여주고 치료영역은 근거 청크의
    K-DST 영역 → area_mapping 으로 뽑는다. 추천까지는 이어갈 수 있다."""
    cfg, names, ev = get_settings(), ctx.names, ctx.evidence
    domains = [e.domain for e in ev if getattr(e, "domain", None)]
    rows = await kb_repo.areas_for_domains(conn, sorted(set(domains)))
    areas = [{"area_code": r["area_code"], "priority": int(r["priority"])} for r in rows]

    lines = ["지금은 설명을 정리해드리지 못했어요. 대신 말씀해주신 내용과 가까운 자료를 찾았어요."]
    for e in ev[:2]:
        lines.append(f"· {e.publisher} 「{e.source_title}」 — {e.content[:120]}")
    if areas:
        names_txt = "·".join(f"**{names.get(a['area_code'], a['area_code'])}**" for a in areas)
        lines.append(f"{names_txt} 영역을 확인해보시면 좋겠어요. 정확한 판단은 소아청소년과나 발달클리닉에서 받아보세요.")
    text = "\n\n".join(lines)

    aid = await repo.insert_answer(conn, session_id=session_id, areas=areas, keywords=["한도초과"],
                                   tier=2, top_k=cfg.top_k, model="fallback")
    await repo.insert_evidence(conn, aid, [(e.chunk_id, i, e.similarity) for i, e in enumerate(ev, 1)])
    await cache.set_json(cache.key("conv", aid), {"answer": text, "age": ctx.age},
                         cfg.session_ttl_hours * 3600)

    return AskResponse(
        answer_id=aid, intent="answer", text=text, highlights=[],
        areas=[AreaPriority(area_code=a["area_code"], area_name=names.get(a["area_code"], a["area_code"]),
                            priority=min(3, max(1, a["priority"]))) for a in areas],
        evidence_count=len(ev), fallback_tier=2, can_recommend=bool(areas),
        ask_region=(bool(areas) and ctx.s["region_id"] is None),
        recommend_for=(aid if areas else None),
        next_prompts=(_tier1_prompts(ctx.age) if areas else await followup_prompts(conn)),
        screen_age_months=_screen_age(ctx.age),
    )


async def ask(conn: asyncpg.Connection, session_id: UUID, message: str) -> AskResponse:
    short, ctx = await _prepare(conn, session_id, message)
    if short is not None:
        return short
    assert ctx is not None
    try:
        out = await gemini().generate_json(prompts.SYSTEM, ctx.user_prompt, schema=prompts.RESPONSE_SCHEMA)
    except GeminiError as e:
        if e.exhausted and ctx.evidence:        # 키가 다 막혔어도 근거는 찾았으니 그대로 보여준다
            return await _degraded(conn, session_id, ctx)
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
        try:
            # 키 교체는 gemini 쪽에서 처리한다 (첫 글자를 내보내기 전까지만)
            async for kind, val in generate_json_stream(prompts.SYSTEM, ctx.user_prompt, schema=prompts.RESPONSE_SCHEMA):
                if kind == "delta":
                    emitted = True
                    yield _sse("delta", {"text": val})
                else:
                    out = val
        except GeminiError as e:
            if e.exhausted and not emitted and ctx.evidence:
                res = await _degraded(conn, session_id, ctx)
                yield _sse("delta", {"text": res.text})
                yield _sse("done", res.model_dump(mode="json"))
                return
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


async def recommend(conn: asyncpg.Connection, *, session_id: UUID, answer_id: UUID | None,
                    area_codes: list[str], region_id: int | None, sido: str | None,
                    max_price: int | None) -> RecommendResponse:
    s = await repo.get_session(conn, session_id)
    if s is None:
        raise ApiError(404, ErrorCode.SESSION_NOT_FOUND, "세션이 없거나 만료되었습니다")

    if answer_id is not None:
        # 대화에서 온 추천 — 그 답변이 뽑은 치료영역을 쓴다
        a = await repo.get_answer(conn, answer_id)
        if a is None:
            raise ApiError(404, ErrorCode.ANSWER_NOT_FOUND, "답변을 찾을 수 없습니다")
        if a["session_id"] != session_id:
            raise ApiError(409, ErrorCode.ANSWER_SESSION_MISMATCH, "이 세션의 답변이 아닙니다")
        if a["fallback_tier"] != 1:
            raise ApiError(409, ErrorCode.ANSWER_NOT_GROUNDED, "근거가 확보된 답변에서만 추천할 수 있습니다")
        import json
        areas = json.loads(a["extracted_areas"]) if isinstance(a["extracted_areas"], str) else a["extracted_areas"]
        want = [x["area_code"] for x in sorted(areas, key=lambda x: x.get("priority", 3))]
    else:
        # 관찰 기록에서 온 추천 — 반응이 약했던 과제의 영역을 그대로 쓴다
        want = [c for c in area_codes if c in VALID_CODES]
        if not want:
            raise ApiError(400, ErrorCode.VALIDATION_ERROR,
                           "추천에 쓸 답변이나 치료영역이 필요합니다",
                           {"area_codes": area_codes})
    names = await kb_repo.area_names(conn)

    # 지역은 추천 시점에 받는다: region_id(시·군·구) > sido(시·도) > 세션에 이미 있는 지역 > 전국
    scope_region: int | None = None      # 시·군·구 id
    scope_label = ""                     # 화면에 쓸 지역 이름
    if region_id is not None:
        picked = await repo.set_session_region(conn, session_id, region_id)
        if picked is None:
            raise ApiError(404, ErrorCode.REGION_NOT_FOUND, "지역을 찾을 수 없습니다")
        scope = picked["sido"]
        scope_region = region_id
        scope_label = f"{picked['sido']} {picked['sigungu']}"
    elif sido:
        scope = sido
        scope_label = sido
        if s["region_id"] is None:
            await repo.set_session_sido(conn, session_id, sido)
    else:
        scope = s["sido"]
        scope_region = s["region_id"]
        scope_label = f"{s['sido']} {s['sigungu']}" if s["sigungu"] else (s["sido"] or "")

    # 전 영역 조합 → 상위 2개 → 1순위 순으로 완화하며 3곳 확보 (고른 구 안에서)
    async def pick(region: int | None) -> list:
        found: list = []
        for k in range(len(want), 0, -1):
            found = await inst_repo.recommend(conn, area_codes=want[:k], region_id=region,
                                              sido=scope, max_price=max_price, limit=3)
            if len(found) >= 3 or k == 1:
                break
        return found

    rows = await pick(scope_region)
    widened = False
    if not rows and scope_region is not None:   # 고른 구에 한 곳도 없으면 시·도로 넓히고 그렇게 말한다
        rows = await pick(None)
        widened = bool(rows)

    items: list[RecommendedInstitution] = []
    for rank, r in enumerate(rows, 1):
        card = to_card(r)
        items.append(RecommendedInstitution(**card.model_dump(), rank=rank, reason=_reason(card, want, names)))
    if answer_id is not None:      # 관찰에서 온 추천은 붙일 답변이 없다
        await repo.insert_recommendations(conn, answer_id, [(i.biz_no, i.rank, i.reason) for i in items])

    want_names = "·".join(names.get(c, c) for c in want[:2])
    where = scope_label or scope or "전국"
    if not items:
        intro = f"{where} 기관 중 조건에 맞는 곳을 찾지 못했어요."
    elif widened:
        intro = (f"{where}에는 조건에 맞는 곳이 없어 {scope} 전체에서 "
                 f"{want_names}을(를) 함께 볼 수 있는 곳 {len(items)}곳을 찾았어요.")
    else:
        intro = f"{where} 기관 중 {want_names}을(를) 함께 볼 수 있는 곳 {len(items)}곳을 찾았어요."
    return RecommendResponse(
        answer_id=answer_id, intro=intro, items=items, scope_sido=scope,
        browse_hint="다른 지역이나 더 많은 기관은 둘러보기에서 지역을 바꿔 확인할 수 있어요.",
    )


# ── 추천 칩 회전 ───────────────────────────────────────────
async def rotating_prompts(conn: asyncpg.Connection) -> list[dict]:
    """첫 화면 칩. 활성 칩 전체(10분 캐시)에서 호출마다 다른 N개."""
    return await _rotate(conn, "home", get_settings().prompt_count)


async def followup_prompts(conn: asyncpg.Connection) -> list[str]:
    """답변 뒤에 붙는 칩. 문구를 코드가 아니라 suggested_prompt 표가 들고 있다.

    표가 비었거나 DB 가 흔들려도 대화가 막다른 길이 되면 안 되므로 코드 기본값으로 떨어진다.
    """
    try:
        rows = await _rotate(conn, "followup", get_settings().followup_count)
    except Exception:                       # 칩 때문에 답변을 실패시키지는 않는다
        log.warning("후속 칩 조회 실패 — 기본값 사용", exc_info=True)
        rows = []
    return [r["text"] for r in rows] or list(prompts.STARTERS)


async def _rotate(conn: asyncpg.Connection, slot: str, n_take: int) -> list[dict]:
    """고정 칩은 항상 앞자리를 지키고, 남는 자리만 회전한다.

    관찰로 들어오는 입구가 매번 보이지 않으면 기능이 있는 줄도 모른다.
    Redis 있으면 라운드로빈(연속 호출이 항상 다른 묶음) · 없으면 무작위.
    """
    import random
    allp = await cache.cached(cache.key("prompts", slot, "v4"), get_settings().cache_ttl_read,
                              lambda: _fetch_prompts(conn, slot))
    pinned = [p for p in allp if p.get("pinned")][:n_take]
    rest = [p for p in allp if not p.get("pinned")]
    left = n_take - len(pinned)
    if left <= 0:
        return pinned
    if len(rest) <= left:
        return pinned + rest
    off = await cache.next_offset(cache.key("prompts", "rr", slot))
    picked = (random.sample(rest, left) if off is None
              else [rest[((off * left) + i) % len(rest)] for i in range(left)])
    return pinned + picked


async def _fetch_prompts(conn: asyncpg.Connection, slot: str) -> list[dict]:
    return [dict(r) for r in await repo.list_prompts(conn, slot)]
