# -*- coding: utf-8 -*-
"""카카오 플레이스 수집 결과(운영시간·홈페이지)를 DB 에 반영한다.

apply_kakao_place.sh 와 하는 일은 같지만 psql/도커 없이 asyncpg 로 붙는다.
이미 값이 있는 칸은 덮어쓰지 않는다 — 공공데이터·기존 값이 우선이다.

사용: DSN=... python scripts/apply_kakao_place.py data/kakao_place_rescue.csv
"""
import asyncio
import csv
import io
import os
import sys

import asyncpg


async def main() -> None:
    path = sys.argv[1] if len(sys.argv) > 1 else "data/kakao_place.csv"
    dsn = os.environ.get("DSN") or sys.exit("DSN 환경변수가 필요합니다")
    rows = [r for r in csv.DictReader(io.open(path, encoding="utf-8-sig"))
            if (r.get("operating_hours") or "").strip() or (r.get("homepage") or "").strip()]

    conn = await asyncpg.connect(dsn)
    before = await conn.fetchrow(
        "SELECT count(operating_hours) h, count(homepage) p, count(*) n FROM institution")
    async with conn.transaction():
        for r in rows:
            await conn.execute(
                """UPDATE institution SET
                     operating_hours = COALESCE(NULLIF(operating_hours,''), NULLIF($2,'')),
                     homepage        = COALESCE(NULLIF(homepage,''),        NULLIF($3,'')),
                     updated_at      = now()
                   WHERE biz_no = $1""",
                r["biz_no"], (r.get("operating_hours") or "").strip(), (r.get("homepage") or "").strip())
    after = await conn.fetchrow(
        "SELECT count(operating_hours) h, count(homepage) p, count(*) n FROM institution")
    print(f"입력 {len(rows)}행")
    print(f"  운영시간 {before['h']} -> {after['h']}  (+{after['h']-before['h']})")
    print(f"  홈페이지 {before['p']} -> {after['p']}  (+{after['p']-before['p']})")
    await conn.execute("SELECT refresh_all_mvs()")
    print("기관 카드 MV 갱신 완료")
    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
