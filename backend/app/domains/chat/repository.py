import json
from uuid import UUID

import asyncpg


# ── 세션 ──
async def create_session(conn: asyncpg.Connection, region_id: int | None,
                         age: int | None, ttl_hours: int) -> asyncpg.Record:
    return await conn.fetchrow(
        """
        INSERT INTO session (region_id, child_age_months, expires_at)
        VALUES ($1, $2, now() + make_interval(hours => $3))
        RETURNING session_id, region_id, child_age_months, to_char(expires_at, 'YYYY-MM-DD"T"HH24:MI:SSOF') AS expires_at
        """,
        region_id, age, ttl_hours,
    )


async def get_session(conn: asyncpg.Connection, session_id: UUID) -> asyncpg.Record | None:
    return await conn.fetchrow(
        """
        SELECT s.session_id, s.region_id, r.sido, s.child_age_months,
               to_char(s.expires_at, 'YYYY-MM-DD"T"HH24:MI:SSOF') AS expires_at
        FROM session s LEFT JOIN region r ON r.region_id = s.region_id
        WHERE s.session_id = $1 AND s.expires_at > now()
        """,
        session_id,
    )


async def patch_session(conn: asyncpg.Connection, session_id: UUID,
                        region_id: int | None, age: int | None) -> None:
    await conn.execute(
        """
        UPDATE session
        SET region_id = COALESCE($2, region_id),
            child_age_months = COALESCE($3, child_age_months)
        WHERE session_id = $1
        """,
        session_id, region_id, age,
    )


async def set_session_region(conn: asyncpg.Connection, session_id: UUID, region_id: int) -> str | None:
    """추천 시점에 고른 지역을 세션에 저장(덮어씀). 해당 시·도명을 돌려준다."""
    return await conn.fetchval(
        """
        WITH r AS (SELECT region_id, sido FROM region WHERE region_id = $2)
        UPDATE session s SET region_id = r.region_id FROM r WHERE s.session_id = $1
        RETURNING r.sido
        """,
        session_id, region_id,
    )


async def latest_grounded_answer(conn: asyncpg.Connection, session_id: UUID) -> asyncpg.Record | None:
    """세션에서 가장 최근의 근거 확보(tier 1) 답변 — '추천해줘' 요청의 기준."""
    return await conn.fetchrow(
        """
        SELECT answer_id, extracted_areas FROM answer
        WHERE session_id = $1 AND fallback_tier = 1
        ORDER BY created_at DESC LIMIT 1
        """,
        session_id,
    )


async def set_session_sido(conn: asyncpg.Connection, session_id: UUID, sido: str) -> None:
    """추천 시 시·도 칩 응답을 세션에 반영 (시·군·구 미상 → 해당 시·도의 첫 region으로 두지 않고 NULL 유지,
    sido는 answer 조회 시 조인용으로만 필요하므로 region이 없으면 갱신하지 않는다)"""
    await conn.execute(
        """
        UPDATE session s SET region_id = COALESCE(s.region_id, (
            SELECT region_id FROM region WHERE sido = $2 ORDER BY sigungu LIMIT 1))
        WHERE s.session_id = $1 AND s.region_id IS NULL
        """,
        session_id, sido,
    )


# ── 답변 ──
async def insert_answer(conn: asyncpg.Connection, *, session_id: UUID, areas: list[dict],
                        keywords: list[str], tier: int, top_k: int, model: str,
                        question_summary: str | None = None) -> UUID:
    return await conn.fetchval(
        """
        INSERT INTO answer (session_id, extracted_areas, intent_keywords, fallback_tier, top_k, model,
                            question_summary)
        VALUES ($1, $2::jsonb, $3, $4, $5, $6, $7)
        RETURNING answer_id
        """,
        session_id, json.dumps(areas, ensure_ascii=False), keywords, tier, top_k, model, question_summary,
    )


async def insert_evidence(conn: asyncpg.Connection, answer_id: UUID,
                          items: list[tuple[str, int, float]]) -> None:
    if items:
        await conn.executemany(
            "INSERT INTO answer_evidence (answer_id, chunk_id, rank, similarity) VALUES ($1,$2,$3,$4::float8)",
            [(answer_id, cid, rank, sim) for cid, rank, sim in items],
        )


async def get_answer(conn: asyncpg.Connection, answer_id: UUID) -> asyncpg.Record | None:
    return await conn.fetchrow(
        "SELECT answer_id, session_id, extracted_areas, fallback_tier FROM answer WHERE answer_id = $1",
        answer_id,
    )


async def list_evidence(conn: asyncpg.Connection, answer_id: UUID) -> list[asyncpg.Record]:
    return await conn.fetch(
        """
        SELECT e.chunk_id, e.chunk_type, e.content, e.publisher, e.source_title,
               e.source_year, e.source_url, ae.similarity
        FROM answer_evidence ae
        JOIN mv_kb_evidence e ON e.chunk_id = ae.chunk_id
        WHERE ae.answer_id = $1
        ORDER BY ae.rank
        """,
        answer_id,
    )


# ── 추천 ──
async def insert_recommendations(conn: asyncpg.Connection, answer_id: UUID,
                                 items: list[tuple[str, int, str]]) -> None:
    await conn.execute("DELETE FROM answer_recommendation WHERE answer_id = $1", answer_id)
    if items:
        await conn.executemany(
            "INSERT INTO answer_recommendation (answer_id, biz_no, rank, reason) VALUES ($1,$2,$3,$4)",
            [(answer_id, b, r, reason) for b, r, reason in items],
        )


async def list_prompts(conn: asyncpg.Connection) -> list[asyncpg.Record]:
    return await conn.fetch(
        "SELECT prompt_id, text, emoji FROM suggested_prompt WHERE active ORDER BY sort_order, prompt_id"
    )
