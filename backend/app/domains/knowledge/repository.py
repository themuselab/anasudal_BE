import asyncpg

EVIDENCE_COLS = "e.chunk_id, e.chunk_type, e.content, e.publisher, e.source_title, e.source_year, e.source_url"


async def vector_search(conn: asyncpg.Connection, qvec: list[float], *,
                        age_months: int | None, top_k: int) -> list[asyncpg.Record]:
    """① 연령 메타 필터 → ② 코사인 최근접. 메타가 없는 청크(제도·질환)는 항상 후보.
    유사도 임계값은 두지 않는다 — 측정에서 분포가 겹쳐 컷이 불가했음."""
    return await conn.fetch(
        f"""
        SELECT {EVIDENCE_COLS},
               c.domain,
               1 - (c.embedding <=> $1::vector) AS similarity
        FROM kb_chunk c
        JOIN mv_kb_evidence e ON e.chunk_id = c.chunk_id
        WHERE c.embedding IS NOT NULL
          AND ($2::int IS NULL
               OR c.age_lo IS NULL
               OR ($2 BETWEEN c.age_lo AND c.age_hi)
               OR ($2 > 71 AND c.age_hi >= 60))
        ORDER BY c.embedding <=> $1::vector
        LIMIT $3
        """,
        qvec, age_months, top_k,
    )


async def get_evidence(conn: asyncpg.Connection, chunk_id: str) -> asyncpg.Record | None:
    return await conn.fetchrow(
        f"SELECT {EVIDENCE_COLS} FROM mv_kb_evidence e WHERE e.chunk_id = $1", chunk_id
    )


async def area_names(conn: asyncpg.Connection) -> dict[str, str]:
    rows = await conn.fetch("SELECT area_code, name FROM therapy_area ORDER BY sort_order")
    return {r["area_code"]: r["name"] for r in rows}


async def areas_for_domains(conn: asyncpg.Connection, domains: list[str]) -> list[asyncpg.Record]:
    """K-DST 영역 이름 → 치료영역 코드 (area_mapping).
    Gemini 키가 모두 한도에 걸렸을 때 LLM 없이 추천 영역을 뽑는 경로."""
    if not domains:
        return []
    return await conn.fetch(
        """
        SELECT area_code, min(priority) AS priority
        FROM area_mapping
        WHERE kdst_domain = ANY($1::text[])
        GROUP BY area_code
        ORDER BY min(priority), area_code
        LIMIT 3
        """,
        domains,
    )
