# -*- coding: utf-8 -*-
"""구조한 카카오 매칭을 받아들일지 판정하고 DB에 반영한다.

TEL·NAME 은 근거가 강하니 그대로 받는다.
NEAR(좌표만 가까운 것)는 실제로 다른 가게가 섞여 있었다 — "일광아동발달센터"가
"일광아트센터미술학원"으로 잡히는 식. 그래서 세 가지를 겹쳐서 본다.
  · 이름 유사도 0.72 이상이면 그대로 받는다
  · 아니면 고유 토큰(하람·솔파란 같은)을 공유하고 + 카카오 업종이 아동·심리·복지 계열이고
    + 50m 안에 있을 때만 받는다
한 장소(place_url)에 두 기관이 걸리면 둘 다 버린다 — 어느 쪽인지 알 수 없다.

사용: DSN=... python scripts/apply_kakao_rescue.py [--dry-run]
"""
import asyncio
import csv
import io
import os
import sys

import asyncpg

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("KAKAO_KEY", "-")  # 매칭 모듈의 정규화 함수만 빌려 쓴다
from match_kakao_rescue import core, norm, sim  # noqa: E402

SIM_OK = 0.72          # 이 이상이면 업종을 안 봐도 같은 곳으로 본다
NEAR_SIM = 0.55        # 업종·거리 조건을 만족할 때의 하한
NEAR_DIST = 50.0       # m
CATEGORY_OK = {"아동상담센터", "심리상담소", "장애인복지시설", "아동복지시설", "사회복지시설",
               "청소년복지시설", "병원", "의원", "연구소", "단체,협회", "교육단체", "클리닉"}


def shares_core(a: str, b: str) -> bool:
    ca, cb = core(a), core(b)
    na, nb = norm(a), norm(b)
    return (len(ca) >= 2 and ca in nb) or (len(cb) >= 2 and cb in na)


def accept(ours: str, rec: dict, category: str) -> bool:
    if rec["why"] in ("TEL", "NAME"):
        return True
    s = float(rec["name_sim"] or 0)
    if s >= SIM_OK:
        return True
    try:
        d = float(rec["dist_m"])
    except (TypeError, ValueError):
        return False
    leaf = category.split(">")[-1].strip()
    return s >= NEAR_SIM and d <= NEAR_DIST and leaf in CATEGORY_OK and shares_core(ours, rec["kakao_name"])


def load(path: str) -> dict[str, dict]:
    return {r["biz_no"]: r for r in csv.DictReader(io.open(path, encoding="utf-8-sig")) if r.get("place_url")}


async def main() -> None:
    dry = "--dry-run" in sys.argv
    dsn = os.environ.get("DSN") or sys.exit("DSN 환경변수가 필요합니다")

    rescue = load("data/kakao_rescue.csv")
    cats = {k: v.get("kakao_category", "") for k, v in load("data/kakao_near_cat.csv").items()}
    names = {r["biz_no"]: r["name"] for r in csv.DictReader(io.open("data/kakao_unmatched.csv", encoding="utf-8-sig"))}

    taken: dict[str, list[str]] = {}
    for biz, rec in rescue.items():
        if accept(names.get(biz, ""), rec, cats.get(biz, "")):
            taken.setdefault(rec["place_url"], []).append(biz)

    dupes = {u: b for u, b in taken.items() if len(b) > 1}
    final = [rescue[b[0]] | {"biz_no": b[0]} for u, b in taken.items() if len(b) == 1]

    by_why: dict[str, int] = {}
    for r in final:
        by_why[r["why"]] = by_why.get(r["why"], 0) + 1
    print(f"후보 {len(rescue):,} -> 채택 {len(final):,}  ({', '.join(f'{k} {v}' for k, v in sorted(by_why.items()))})")
    if dupes:
        print(f"  한 장소에 2곳 이상 걸려 제외: {len(dupes)}장소 {sum(len(b) for b in dupes.values())}곳")
    if dry:
        return

    conn = await asyncpg.connect(dsn)
    stats = {"place_url": 0, "tel": 0, "coord": 0, "addr": 0}
    async with conn.transaction():
        for r in final:
            row = await conn.fetchrow(
                "SELECT tel, lat, lon, address FROM institution WHERE biz_no=$1", r["biz_no"])
            if row is None:
                continue
            tel = r["kakao_tel"].strip() or None
            try:
                lat, lon = float(r["kakao_y"]), float(r["kakao_x"])
            except (TypeError, ValueError):
                lat = lon = None
            addr = r["kakao_addr"].strip() or None
            await conn.execute(
                """UPDATE institution SET
                     place_url  = $2,
                     tel        = COALESCE(tel, $3),
                     lat        = COALESCE(lat, $4),
                     lon        = COALESCE(lon, $5),
                     address    = COALESCE(address, $6),
                     match_conf = $7
                   WHERE biz_no = $1""",
                r["biz_no"], r["place_url"], tel, lat, lon, addr, f"RESCUE_{r['why']}")
            stats["place_url"] += 1
            stats["tel"] += bool(tel and not row["tel"])
            stats["coord"] += bool(lat and row["lat"] is None)
            stats["addr"] += bool(addr and not row["address"])
    await conn.close()
    print(f"반영: 카카오링크 +{stats['place_url']}, 전화 +{stats['tel']}, 좌표 +{stats['coord']}, 주소 +{stats['addr']}")


if __name__ == "__main__":
    asyncio.run(main())
