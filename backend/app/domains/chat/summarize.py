"""질문 요약을 백그라운드로 만들어 DB 에 채운다.

사용자 응답이 끝난 뒤에 돌기 때문에 답변 속도에 영향이 없고, 전용 키를 써서 답변 쿼터도 건드리지 않는다.
요약이 실패해도 사용자에게는 아무 일도 일어나지 않는다 — `answer.question_summary` 가 비어 있을 뿐이다.
원문은 이 작업 중 메모리에만 잠깐 있고 DB 에는 요약만 남는다.
"""
import asyncio
import logging
from uuid import UUID

from app.core.db import connection
from app.core.gemini import gemini

log = logging.getLogger("anasudal.summarize")

# 작업이 가비지 컬렉션으로 사라지지 않게 붙잡아 둔다
_running: set[asyncio.Task[None]] = set()


def schedule(answer_id: UUID, message: str, age_months: int | None) -> None:
    """응답을 보낸 뒤 호출. 기다리지 않는다."""
    task = asyncio.create_task(_run(answer_id, message, age_months))
    _running.add(task)
    task.add_done_callback(_running.discard)


async def _run(answer_id: UUID, message: str, age_months: int | None) -> None:
    try:
        summary = await gemini().summarize_question(message, age_months)
        if not summary:
            return
        async with connection() as conn:
            await conn.execute(
                "UPDATE answer SET question_summary = $2 WHERE answer_id = $1 AND question_summary IS NULL",
                answer_id, summary,
            )
            # 이미 피드백을 눌러 학습 표본이 만들어졌다면 거기에도 채워준다
            await conn.execute(
                "UPDATE training_sample SET question_summary = $2 WHERE answer_id = $1 AND question_summary IS NULL",
                answer_id, summary,
            )
    except asyncio.CancelledError:
        raise
    except Exception as e:                       # 백그라운드라 무슨 일이 있어도 앱을 흔들지 않는다
        log.warning("요약 저장 실패 (answer=%s): %s", answer_id, e)


async def drain(timeout: float = 3.0) -> None:
    """종료 시 돌고 있는 요약 작업을 잠깐 기다린다."""
    if not _running:
        return
    await asyncio.wait(set(_running), timeout=timeout)
