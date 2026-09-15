import json
from uuid import UUID

import asyncpg


async def tasks_for_age(conn: asyncpg.Connection, age_months: int) -> list[asyncpg.Record]:
    return await conn.fetch(
        """
        SELECT t.task_code, t.title, t.tool, t.skippable, t.observes, t.area_codes,
               (SELECT json_agg(json_build_object('step_no', s.step_no, 'script', s.script,
                                                  'wait_sec', s.wait_sec) ORDER BY s.step_no)
                  FROM screening_step s WHERE s.task_code = t.task_code) AS steps,
               (SELECT json_agg(json_build_object('option_no', o.option_no, 'label', o.label)
                                ORDER BY o.option_no)
                  FROM screening_option o WHERE o.task_code = t.task_code) AS options
        FROM screening_task t
        WHERE t.active AND $1 BETWEEN t.age_lo AND t.age_hi
        ORDER BY t.sort_order, t.task_code
        """,
        age_months,
    )


async def save_result(conn: asyncpg.Connection, *, age_months: int, answers: list[dict],
                      skipped: list[str], area_codes: list[str]) -> asyncpg.Record:
    return await conn.fetchrow(
        """
        INSERT INTO screening_result (child_age_months, answers, skipped, area_codes)
        VALUES ($1, $2::jsonb, $3::text[], $4::text[])
        RETURNING result_token, created_at, expires_at
        """,
        age_months, json.dumps(answers, ensure_ascii=False), skipped, area_codes,
    )


async def get_result(conn: asyncpg.Connection, token: UUID) -> asyncpg.Record | None:
    return await conn.fetchrow(
        """SELECT result_token, child_age_months, answers, skipped, area_codes, expires_at
           FROM screening_result WHERE result_token = $1 AND expires_at > now()""",
        token,
    )


async def delete_result(conn: asyncpg.Connection, token: UUID) -> bool:
    row = await conn.fetchrow(
        "DELETE FROM screening_result WHERE result_token = $1 RETURNING result_token", token)
    return row is not None
