from uuid import UUID

import asyncpg


async def list_reasons(conn: asyncpg.Connection) -> list[asyncpg.Record]:
    return await conn.fetch("SELECT reason_code, label FROM feedback_reason ORDER BY sort_order")


async def upsert(conn: asyncpg.Connection, answer_id: UUID, rating: str, reason: str | None) -> asyncpg.Record:
    """답변당 1회. 다시 누르면 덮어쓴다."""
    return await conn.fetchrow(
        """
        INSERT INTO feedback (answer_id, rating, reason_code)
        VALUES ($1, $2, $3)
        ON CONFLICT (answer_id) DO UPDATE
          SET rating = EXCLUDED.rating, reason_code = EXCLUDED.reason_code, created_at = now()
        RETURNING feedback_id, answer_id, rating, reason_code
        """,
        answer_id, rating, reason,
    )


async def upsert_training_sample(conn: asyncpg.Connection, answer_id: UUID, rating: str, reason: str | None,
                                 answer_text: str | None, child_age_months: int | None) -> None:
    """👍👎가 눌린 답변만 학습 표본으로. 질문은 요약(answer.question_summary), 원문은 없다."""
    await conn.execute(
        """
        INSERT INTO training_sample (answer_id, rating, reason_code, question_summary, answer_text,
                                     child_age_months, fallback_tier, extracted_areas, intent_keywords,
                                     evidence, recommended, model)
        SELECT a.answer_id, $2, $3, a.question_summary, $4, COALESCE($5, s.child_age_months),
               a.fallback_tier, a.extracted_areas, a.intent_keywords,
               (SELECT COALESCE(jsonb_agg(jsonb_build_object('chunk_id', e.chunk_id, 'rank', e.rank,
                                                            'similarity', e.similarity) ORDER BY e.rank), '[]'::jsonb)
                  FROM answer_evidence e WHERE e.answer_id = a.answer_id),
               (SELECT COALESCE(array_agg(r.biz_no ORDER BY r.rank), '{}')
                  FROM answer_recommendation r WHERE r.answer_id = a.answer_id),
               a.model
        FROM answer a LEFT JOIN session s ON s.session_id = a.session_id
        WHERE a.answer_id = $1
        ON CONFLICT (answer_id) DO UPDATE
          SET rating = EXCLUDED.rating, reason_code = EXCLUDED.reason_code,
              answer_text = COALESCE(EXCLUDED.answer_text, training_sample.answer_text),
              recommended = EXCLUDED.recommended, rated_at = now()
        """,
        answer_id, rating, reason, answer_text, child_age_months,
    )
