"""asyncpg 커넥션 풀. ORM 없이 SQL을 그대로 쓴다 — DDL·MV와 1:1로 대응시키기 위해."""
from contextlib import asynccontextmanager
from typing import AsyncIterator

import asyncpg
from pgvector.asyncpg import register_vector

from app.core.config import get_settings

_pool: asyncpg.Pool | None = None


async def _init_conn(conn: asyncpg.Connection) -> None:
    await register_vector(conn)          # vector 타입 ↔ list[float]/ndarray


async def open_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            get_settings().database_url, min_size=2, max_size=10, init=_init_conn
        )
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def pool() -> asyncpg.Pool:
    assert _pool is not None, "DB pool not initialised"
    return _pool


@asynccontextmanager
async def connection() -> AsyncIterator[asyncpg.Connection]:
    async with pool().acquire() as conn:
        yield conn


async def get_conn() -> AsyncIterator[asyncpg.Connection]:
    """FastAPI Depends 용"""
    async with pool().acquire() as conn:
        yield conn
