"""조기 관찰 — 과제를 내주고, 부모가 고른 답을 기록으로 돌려준다.

판정하지 않는다. 점수도 등급도 내지 않는다.
근거가 되는 논문에서 과제 성공/실패만 쓴 모델은 AUROC 0.76 이었고, 그것도
"고위험 vs 확진"을 가르는 2단계 과제였다. 0.93 은 SRS 설문 텍스트를 함께 넣었을 때의
값이고 그 설문은 라이선스가 있어 쓸 수 없다. 우리에겐 그 약한 조각 하나뿐이다.
그래서 결과는 "오늘 이렇게 관찰됐다"는 기록이고, 판단은 전문기관이 한다.
"""
import json
from typing import Any
from uuid import UUID

import asyncpg

from app.core.errors import ApiError, ErrorCode
from app.domains.screening import repository as repo
from app.domains.screening.schemas import (Observation, ResultIn, ResultOut, Task, TaskOption,
                                           TaskSet, TaskStep)

# 이 번호부터는 "오늘은 반응이 약했어요" 로 본다.
# 1·2 는 스스로 또는 한 번 더 보여주니 반응한 것, 3·4 는 짚어줘야 하거나 반응이 없던 것.
ATTENTION_FROM = 3


def _json(v: Any) -> list[dict]:
    """asyncpg 는 json/jsonb 를 문자열로 준다 (풀에 코덱을 걸지 않았다).
    풀 설정을 건드리면 다른 도메인까지 영향이 가므로 여기서만 푼다."""
    if v is None:
        return []
    return json.loads(v) if isinstance(v, str) else list(v)


def _task(r: asyncpg.Record) -> Task:
    return Task(
        task_code=r["task_code"], title=r["title"], tool=r["tool"], skippable=r["skippable"],
        observes=r["observes"],
        steps=[TaskStep(**s) for s in _json(r["steps"])],
        options=[TaskOption(**o) for o in _json(r["options"])],
    )


async def task_set(conn: asyncpg.Connection, age_months: int) -> TaskSet:
    if not 18 <= age_months <= 48:
        raise ApiError(400, ErrorCode.VALIDATION_ERROR,
                       "18~48개월 아이를 대상으로 만들어졌어요",
                       {"child_age_months": age_months})
    rows = await repo.tasks_for_age(conn, age_months)
    tasks = [_task(r) for r in rows]
    return TaskSet(
        child_age_months=age_months,
        tools=[t.tool for t in tasks if t.tool],
        tasks=tasks,
    )


def _headline(done: int, attention: int) -> tuple[str, str]:
    """결과 한 줄과 안내 문구. 어느 쪽이든 판정처럼 들리지 않게 쓴다."""
    if done == 0:
        return ("오늘은 살펴본 과제가 없어요",
                "준비물이 있을 때 다시 해보시면 아이 모습을 더 볼 수 있어요.")
    if attention == 0:
        return (f"오늘 {done}가지를 살펴봤고, 모두 반응이 있었어요",
                "한 번의 관찰이라 이걸로 판단하긴 어려워요. 걱정되는 모습이 계속되면 "
                "소아청소년과나 발달클리닉에서 확인해보세요.")
    return (f"오늘 {done}가지 중 {attention}가지에서 반응이 약했어요",
            "이건 진단이 아니라 참고용 기록이에요. 아이 컨디션이나 그날 상황에 따라 "
            "달라질 수 있어서, 이 결과를 가지고 전문기관에 문의해보시는 게 가장 정확해요.")


async def build_result(conn: asyncpg.Connection, body: ResultIn) -> ResultOut:
    rows = await repo.tasks_for_age(conn, body.child_age_months)
    by_code = {r["task_code"]: r for r in rows}

    obs: list[Observation] = []
    areas: list[str] = []
    for a in body.answers:
        r = by_code.get(a.task_code)
        if r is None:                       # 연령에 없는 과제는 조용히 버린다
            continue
        label = next((o["label"] for o in _json(r["options"]) if o["option_no"] == a.option_no), "")
        weak = a.option_no >= ATTENTION_FROM
        obs.append(Observation(task_code=a.task_code, title=r["title"], observes=r["observes"],
                               label=label, needs_attention=weak))
        if weak:
            areas += [c for c in (r["area_codes"] or []) if c not in areas]

    attention = [o.title for o in obs if o.needs_attention]
    # 건너뛴 과제는 기록만 하고 신호에 섞지 않는다 — 준비물 유무는 아이가 아니라 집 사정이다
    skipped = [s for s in body.skipped if s in by_code]

    saved = await repo.save_result(
        conn, age_months=body.child_age_months,
        answers=[a.model_dump() for a in body.answers], skipped=skipped, area_codes=areas)

    headline, note = _headline(len(obs), len(attention))
    return ResultOut(
        result_token=saved["result_token"], child_age_months=body.child_age_months,
        done_count=len(obs), skipped_count=len(skipped), observations=obs,
        attention=attention, area_codes=areas, headline=headline, note=note,
        suggest_visit=bool(attention), expires_at=saved["expires_at"].isoformat(),
    )


async def read_result(conn: asyncpg.Connection, token: UUID) -> ResultOut:
    row = await repo.get_result(conn, token)
    if row is None:
        raise ApiError(404, ErrorCode.NOT_FOUND, "결과를 찾을 수 없거나 보관 기간이 지났어요")
    rows = await repo.tasks_for_age(conn, row["child_age_months"])
    by_code = {r["task_code"]: r for r in rows}

    obs: list[Observation] = []
    for a in _json(row["answers"]):
        r = by_code.get(a["task_code"])
        if r is None:
            continue
        label = next((o["label"] for o in _json(r["options"]) if o["option_no"] == a["option_no"]), "")
        obs.append(Observation(task_code=a["task_code"], title=r["title"], observes=r["observes"],
                               label=label, needs_attention=a["option_no"] >= ATTENTION_FROM))

    attention = [o.title for o in obs if o.needs_attention]
    headline, note = _headline(len(obs), len(attention))
    return ResultOut(
        result_token=row["result_token"], child_age_months=row["child_age_months"],
        done_count=len(obs), skipped_count=len(row["skipped"] or []), observations=obs,
        attention=attention, area_codes=list(row["area_codes"] or []),
        headline=headline, note=note, suggest_visit=bool(attention),
        expires_at=row["expires_at"].isoformat(),
    )


async def remove_result(conn: asyncpg.Connection, token: UUID) -> None:
    if not await repo.delete_result(conn, token):
        raise ApiError(404, ErrorCode.NOT_FOUND, "결과를 찾을 수 없어요")
