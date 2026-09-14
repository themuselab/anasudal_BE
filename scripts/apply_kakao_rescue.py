# -*- coding: utf-8 -*-
"""구조한 카카오 매칭을 받아들일지 판정하고 DB에 반영한다.

근거마다 믿을 만한 정도가 다르다.

TEL  전화번호가 같다. 보통은 결정적이지만, 전화번호로 직접 검색하면 번호를
     물려받았거나 같은 사무실을 쓰는 남의 가게가 걸린다 — "압량언어심리상담센터"가
     "선스크린골프연습장"으로, "㈜디디다"가 22km 떨어진 "대덕정밀"로 잡혔다.
     그래서 이름이 어느 정도 닮았을 때(0.45+)만 그대로 받고, 그보다 낮으면
     고유 토큰을 공유하면서 카카오 업종도 아동·심리·복지 계열일 때만 받는다.
NAME 정규화한 이름이 서로를 품는다. 그대로 받는다.
ADDR 도로명 건물이 같다. 한 건물에 여러 업소가 있으니 업종까지 본다.
NEAR 좌표만 가깝다. 제일 약하다 — "일광아동발달센터"가 "일광아트센터미술학원"으로
     잡히는 식이라 유사도 0.72 이상이거나, 고유 토큰 공유 + 업종 + 50m 를 모두
     만족할 때만 받는다.

한 장소(place_url)에 두 기관이 걸리면 둘 다 버린다 — 어느 쪽인지 알 수 없다.
애매한 걸 넣느니 빈칸이 낫다. 상세 화면에 엉뚱한 지도가 뜨는 쪽이 더 나쁘다.

사용: DSN=... python scripts/apply_kakao_rescue.py [입력.csv] [--dry-run] [--show-rejects]
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

SIM_OK = 0.72          # NEAR: 이 이상이면 업종을 안 봐도 같은 곳으로 본다
NEAR_SIM = 0.55        # NEAR: 업종·거리 조건을 만족할 때의 하한
NEAR_DIST = 50.0       # m
TEL_SIM = 0.45         # TEL: 이 아래면 업종·고유 토큰까지 봐야 받는다
ADDR_DIST = 100.0      # ADDR: 같은 건물이라면 이 안에 있어야 한다
CATEGORY_OK = {"아동상담센터", "심리상담소", "상담", "장애인복지시설", "아동복지시설",
               "사회복지시설", "청소년복지시설", "사회복지단체", "병원", "의원", "클리닉",
               "연구소", "단체,협회", "교육단체", "보청기", "특수학교", "재활원"}


def shares_core(a: str, b: str) -> bool:
    ca, cb = core(a), core(b)
    na, nb = norm(a), norm(b)
    return (len(ca) >= 2 and ca in nb) or (len(cb) >= 2 and cb in na)


def accept(ours: str, rec: dict, category: str) -> tuple[bool, str]:
    """받아들일지와 그 이유. 이유는 사람이 결과를 훑어볼 때 쓴다."""
    s = float(rec["name_sim"] or 0)
    try:
        d: float | None = float(rec["dist_m"])
    except (TypeError, ValueError):
        d = None
    leaf = category.split(">")[-1].strip()
    cat_ok = leaf in CATEGORY_OK
    cored = shares_core(ours, rec["kakao_name"])

    if rec["why"] == "NAME":
        return True, "이름 포함"
    if rec["why"] == "TEL":
        if s >= TEL_SIM:
            return True, "전화+이름"
        if cored and cat_ok:
            return True, "전화+고유어+업종"
        return False, f"전화만 일치 (유사도 {s:.2f}, 업종 {leaf or '?'})"
    if rec["why"] == "ADDR":
        if cat_ok and (d is None or d <= ADDR_DIST):
            return True, "같은 건물+업종"
        return False, f"같은 건물이나 업종 {leaf or '?'}"
    # NEAR
    if s >= SIM_OK:
        return True, "좌표+이름"
    if d is not None and d <= NEAR_DIST and cat_ok and cored and s >= NEAR_SIM:
        return True, "좌표+고유어+업종"
    return False, f"좌표만 가까움 (유사도 {s:.2f}, 업종 {leaf or '?'})"


def load(path: str) -> dict[str, dict]:
    return {r["biz_no"]: r for r in csv.DictReader(io.open(path, encoding="utf-8-sig")) if r.get("place_url")}


async def main() -> None:
    dry = "--dry-run" in sys.argv
    show = "--show-rejects" in sys.argv
    dsn = os.environ.get("DSN") or sys.exit("DSN 환경변수가 필요합니다")
    src = next((a for a in sys.argv[1:] if a.endswith(".csv")), "data/kakao_rescue.csv")
    unmatched = src.replace("kakao_rescue", "kakao_unmatched").replace("2.csv", "2.csv")

    rescue = load(src)
    # 1차 결과는 업종을 안 받아왔다 — NEAR 만 따로 다시 받아둔 파일이 있다
    cats = {k: v.get("kakao_category", "") for k, v in load("data/kakao_near_cat.csv").items()}
    for k, v in rescue.items():
        if v.get("kakao_category"):
            cats[k] = v["kakao_category"]
    names = {r["biz_no"]: r["name"] for r in csv.DictReader(io.open(unmatched, encoding="utf-8-sig"))}

    taken: dict[str, list[str]] = {}
    rejects: list[str] = []
    for biz, rec in rescue.items():
        ok, why = accept(names.get(biz, ""), rec, cats.get(biz, ""))
        if ok:
            taken.setdefault(rec["place_url"], []).append(biz)
        else:
            rejects.append(f"  [{rec['why']}] {names.get(biz,'')[:22]:<24} -> "
                           f"{rec['kakao_name'][:24]:<26} {why}")
    if show and rejects:
        print(f"── 버린 {len(rejects)}건 ──")
        print(chr(10).join(rejects))
        print()

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
    await conn.execute("SELECT refresh_all_mvs()")   # 기관 카드가 place_url 을 들고 있다
    await conn.close()
    print(f"반영: 카카오링크 +{stats['place_url']}, 전화 +{stats['tel']}, 좌표 +{stats['coord']}, 주소 +{stats['addr']}")


if __name__ == "__main__":
    asyncio.run(main())
