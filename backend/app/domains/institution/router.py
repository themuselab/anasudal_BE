from fastapi import APIRouter, Depends, Query
from fastapi.encoders import jsonable_encoder
import asyncpg

from app.core import cache
from app.core.config import get_settings
from app.core.db import get_conn
from app.core.envelope import EnvelopeRoute
from app.domains.institution import service
from app.domains.institution.schemas import InstitutionDetail, InstitutionPage

router = APIRouter(route_class=EnvelopeRoute, prefix="/institutions", tags=["institution"])


@router.get("", response_model=InstitutionPage, summary="둘러보기 리스트 (지역 필터 · 기관명/치료영역 검색 · 정렬)")
async def browse(
    sido: str | None = Query(None, description="시·도명. 미설정 시 전국"),
    region_id: int | None = Query(None, description="시·군·구 id. 주면 sido 무시"),
    q: str | None = Query(None, max_length=50, description="기관 이름 또는 치료영역 (예: 발달센터, 언어치료, 감각통합)"),
    sort: str = Query("recommended", pattern="^(recommended|price)$",
                      description="recommended = 제공 영역이 많은 순 · price = 회기당 최저 단가 낮은 순"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    conn: asyncpg.Connection = Depends(get_conn),
):
    return await cache.cached(
        cache.key("inst", "browse", sido or "-", region_id or "-", (q or "-").strip().lower(), sort, page, size),
        get_settings().cache_ttl_read,
        lambda: _json(service.browse(conn, sido=sido, region_id=region_id, q=q, sort=sort, page=page, size=size)))


@router.get("/{biz_no}", response_model=InstitutionDetail, summary="기관 상세 (비용 표 포함)")
async def detail(biz_no: str, conn: asyncpg.Connection = Depends(get_conn)):
    return await cache.cached(cache.key("inst", "detail", biz_no), get_settings().cache_ttl_read,
                              lambda: _json(service.detail(conn, biz_no)))


async def _json(coro):
    return jsonable_encoder(await coro)
