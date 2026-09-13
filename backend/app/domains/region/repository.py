import asyncpg


async def list_sido(conn: asyncpg.Connection) -> list[asyncpg.Record]:
    return await conn.fetch(
        """
        SELECT sido, count(*)::int AS institution_count
        FROM mv_institution_card
        WHERE sido IS NOT NULL
        GROUP BY sido
        ORDER BY sido
        """
    )


async def list_sigungu(conn: asyncpg.Connection, sido: str) -> list[asyncpg.Record]:
    return await conn.fetch(
        """
        SELECT r.region_id, r.sido, r.sigungu,
               count(c.biz_no)::int AS institution_count
        FROM region r
        LEFT JOIN mv_institution_card c ON c.region_id = r.region_id
        WHERE r.sido = $1
        GROUP BY r.region_id, r.sido, r.sigungu
        ORDER BY r.sigungu
        """,
        sido,
    )
