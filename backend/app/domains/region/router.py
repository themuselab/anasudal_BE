from fastapi import APIRouter, Depends
import asyncpg

from app.core import cache
from app.core.config import get_settings
from app.core.db import get_conn
from app.core.envelope import EnvelopeRoute
from app.domains.region import repository as repo
from app.domains.region.schemas import Region, Sido

router = APIRouter(route_class=EnvelopeRoute, prefix="/regions", tags=["region"])


@router.get("/sido", response_model=list[Sido], summary="시·도 목록 (위치 설정 1단계)")
async def sido_list(conn: asyncpg.Connection = Depends(get_conn)):
    return await cache.cached(cache.key("sido"), get_settings().cache_ttl_read,
                              lambda: _rows(repo.list_sido(conn)))


@router.get("", response_model=list[Region], summary="시·군·구 목록")
async def sigungu_list(sido: str, conn: asyncpg.Connection = Depends(get_conn)):
    return await cache.cached(cache.key("sigungu", sido), get_settings().cache_ttl_read,
                              lambda: _rows(repo.list_sigungu(conn, sido)))


async def _rows(coro):
    return [dict(r) for r in await coro]
