# -*- coding: utf-8 -*-
"""서울 수집분(seouli_clinics·seoul_final)에 있는 기관 자체 홈페이지를 DB 에 채운다.

전국 마스터(nationwide_master.csv)는 이미 DB 에 전부 반영돼 있어 새로 얻을 게 없다.
서울 쪽 두 파일에만 남아 있는 값이 있어서 이것만 가져온다.

붙이는 기준: biz_no 가 있으면 그걸로, 없으면 정규화한 이름이 서울 안에서
유일할 때만. 이미 값이 있는 칸은 건드리지 않는다.

사용: DSN=... python scripts/apply_local_homepage.py [--dry-run]
"""
import asyncio
import collections
import csv
import io
import os
import sys

import asyncpg

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("KAKAO_KEY", "-")
from match_kakao_rescue import norm  # noqa: E402


def rows_of(path: str) -> list[dict]:
    try:
        return list(csv.DictReader(io.open(path, encoding="utf-8-sig")))
    except FileNotFoundError:
        return []


async def main() -> None:
    dry = "--dry-run" in sys.argv
    dsn = os.environ.get("DSN") or sys.exit("DSN 환경변수가 필요합니다")

    conn = await asyncpg.connect(dsn)
    inst = await conn.fetch("""SELECT i.biz_no, i.name, i.homepage, r.sido
        FROM institution i LEFT JOIN region r ON r.region_id = i.region_id""")

    by_biz = {i["biz_no"]: i for i in inst}
    seoul = collections.defaultdict(list)
    for i in inst:
        if (i["sido"] or "").startswith("서울"):
            seoul[norm(i["name"])].append(i)

    found: dict[str, str] = {}
    for path in ("data/seouli_clinics.csv", "data/seoul_final.csv"):
        for r in rows_of(path):
            url = (r.get("homepage") or "").strip()
            if not url.startswith("http"):
                continue
            i = by_biz.get((r.get("biz_no") or "").strip())
            if i is None:
                cand = seoul.get(norm(r.get("name", "")))
                if not cand or len(cand) > 1:      # 동명이 둘이면 어느 쪽인지 모른다
                    continue
                i = cand[0]
            if not i["homepage"]:
                found.setdefault(i["biz_no"], url)

    print(f"채울 홈페이지 {len(found)}곳")
    if dry:
        await conn.close()
        return

    async with conn.transaction():
        for biz, url in found.items():
            await conn.execute(
                """UPDATE institution SET homepage = $2, updated_at = now()
                   WHERE biz_no = $1 AND (homepage IS NULL OR homepage = '')""", biz, url)
    await conn.execute("SELECT refresh_all_mvs()")
    r = await conn.fetchrow("SELECT count(homepage) h, count(*) n FROM institution")
    print(f"반영 후 홈페이지 {r['h']} / {r['n']}")
    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
