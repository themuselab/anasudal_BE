import asyncpg

from app.domains.institution.areas import match_area_codes

CARD_COLS = """
  biz_no, name, sido, sigungu, area_codes, area_names,
  price_min, price_max, price_year, visit_available, link_url, has_own_site
"""

# 둘러보기 정렬 — 화면의 칩 두 개와 1:1
ORDER_BY = {
    # 한 곳에서 여러 영역을 볼 수 있는 기관이 먼저. 점수는 화면에 내보내지 않고 순서로만 쓴다
    "recommended": 'cardinality(area_codes) DESC, name COLLATE "C"',
    # 회기당 최저 단가가 싼 순. 단가 없는 곳은 뒤로
    "price": 'price_min ASC NULLS LAST, name COLLATE "C"',
}


async def search(conn: asyncpg.Connection, *, sido: str | None, region_id: int | None,
                 q: str | None, sort: str, page: int, size: int) -> tuple[int, list[asyncpg.Record]]:
    """둘러보기. 필터는 지역, 검색은 기관명 + 치료영역, 정렬은 추천순/비용순."""
    where = ["1=1"]
    args: list = []

    if region_id is not None:
        args.append(region_id)
        where.append(f"region_id = ${len(args)}")
    elif sido:
        args.append(sido)
        where.append(f"sido = ${len(args)}")

    if q and q.strip():
        term = q.strip()
        args.append(f"%{term}%")
        name_cond = f"name ILIKE ${len(args)}"
        codes = match_area_codes(term)          # "언어치료" → SPEECH 처럼 부모가 쓰는 말도 잡는다
        if codes:
            args.append(codes)
            where.append(f"({name_cond} OR area_codes::text[] && ${len(args)}::text[])")
        else:
            where.append(name_cond)

    w = " AND ".join(where)
    order = ORDER_BY.get(sort, ORDER_BY["recommended"])

    total = await conn.fetchval(f"SELECT count(*) FROM mv_institution_card WHERE {w}", *args)
    args += [size, (page - 1) * size]
    rows = await conn.fetch(
        f"""
        SELECT {CARD_COLS}
        FROM mv_institution_card
        WHERE {w}
        ORDER BY {order}
        LIMIT ${len(args) - 1} OFFSET ${len(args)}
        """,
        *args,
    )
    return int(total), rows


async def get_card(conn: asyncpg.Connection, biz_no: str) -> asyncpg.Record | None:
    return await conn.fetchrow(
        f"SELECT {CARD_COLS}, address, tel, lat, lon, operating_hours FROM mv_institution_card WHERE biz_no = $1",
        biz_no,
    )


async def get_prices(conn: asyncpg.Connection, biz_no: str) -> list[asyncpg.Record]:
    return await conn.fetch(
        """
        SELECT p.area_code, a.name AS area_name, p.delivery_mode, p.price_krw, p.price_year,
               to_char(p.disclosed_at, 'YYYY-MM-DD') AS disclosed_at
        FROM institution_area_price p
        JOIN therapy_area a ON a.area_code = p.area_code
        WHERE p.biz_no = $1
          AND p.price_year = (SELECT max(price_year) FROM institution_area_price WHERE biz_no = $1)
        ORDER BY a.sort_order, p.delivery_mode
        """,
        biz_no,
    )


async def recommend(conn: asyncpg.Connection, *, area_codes: list[str], sido: str | None,
                    max_price: int | None, limit: int = 3) -> list[asyncpg.Record]:
    """추천: 요구 영역과 겹치는 수(정확도) → 전 영역 포함 여부 → 단가 → 이름 순.
    회의 결정대로 점수는 화면에 내보내지 않고 순서로만 쓴다."""
    return await conn.fetch(
        f"""
        SELECT {CARD_COLS},
               cardinality(ARRAY(SELECT unnest(area_codes::text[]) INTERSECT SELECT unnest($1::text[]))) AS matched
        FROM mv_institution_card
        WHERE area_codes::text[] && $1::text[]
          AND ($2::text IS NULL OR sido = $2)
          AND ($3::int  IS NULL OR price_min <= $3)
        ORDER BY matched DESC, (area_codes::text[] @> $1::text[]) DESC, price_min ASC NULLS LAST, name COLLATE "C"
        LIMIT $4
        """,
        area_codes, sido, max_price, limit,
    )
