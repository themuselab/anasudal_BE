import asyncpg

from app.core.errors import ApiError, ErrorCode

from app.domains.institution import repository as repo
from app.domains.institution.schemas import InstitutionCard, InstitutionDetail, InstitutionPage, PriceRow


def to_card(r: asyncpg.Record) -> InstitutionCard:
    d = dict(r)
    d["area_codes"] = list(d.get("area_codes") or [])
    d["area_names"] = list(d.get("area_names") or [])
    return InstitutionCard(**{k: d[k] for k in InstitutionCard.model_fields if k in d})


async def browse(conn, *, sido, region_id, q, sort, page, size) -> InstitutionPage:
    total, rows = await repo.search(conn, sido=sido, region_id=region_id, q=q, sort=sort, page=page, size=size)
    return InstitutionPage(total=total, items=[to_card(r) for r in rows], page=page, size=size)


async def detail(conn, biz_no: str) -> InstitutionDetail:
    r = await repo.get_card(conn, biz_no)
    if r is None:
        raise ApiError(404, ErrorCode.INSTITUTION_NOT_FOUND, "기관을 찾을 수 없습니다")
    prices = [PriceRow(**dict(p)) for p in await repo.get_prices(conn, biz_no)]
    card = to_card(r)
    year = prices[0].price_year if prices else card.price_year
    return InstitutionDetail(
        **card.model_dump(),            # tel 은 카드가 들고 있다 — 여기서 또 주면 중복 인자로 터진다
        address=r["address"],
        lat=float(r["lat"]) if r["lat"] is not None else None,
        lon=float(r["lon"]) if r["lon"] is not None else None,
        operating_hours=r["operating_hours"],
        prices=prices,
        price_note=f"{year}년 공시 기준 · 변동될 수 있어요" if year else "공시 단가 없음",
    )
