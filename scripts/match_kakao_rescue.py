# -*- coding: utf-8 -*-
"""카카오맵 매칭에 실패한 기관을 다시 찾는다.

앞선 enrich_kakao.py 는 "이름"만으로 검색하고 주소·지역번호로 검증했다.
그래서 이름이 조금 다르면(법인명 접두사, 오타, 상호 변경) 전부 떨어졌다 — 816곳.

여기서는 세 가지를 더 쓴다.
  1. 좌표 반경 검색  — 95% 가 좌표를 갖고 있다. 반경 700m 안이면 후보가 몇 개로 준다.
  2. 핵심 토큰 검색  — "○○아동발달센터" 에서 흔한 꼬리말을 떼고 "○○" 로 찾는다.
  3. 전화번호 대조   — 번호가 같으면 이름이 달라도 같은 곳이다. 가장 강한 근거.

받아들이는 기준 (엄격 → 느슨)
  TEL     전화번호 완전 일치
  NAME    정규화한 이름이 같거나 포함 + 같은 시·군·구
  NEAR    좌표 300m 이내 + 이름 유사도 0.55 이상 + 같은 시·군·구
그 외는 버린다. 애매한 걸 넣느니 빈칸이 낫다.

사용:
  KAKAO_KEY=<REST키> python scripts/match_kakao_rescue.py 입력.csv 출력.csv [건수] [--resume] [--rps=4]
  입력 CSV 열: biz_no, name, address, tel, sido, sigungu, lat, lon
"""
import csv
import io
import math
import os
import re
import sys
import time
from difflib import SequenceMatcher

import httpx

KEY = os.environ.get("KAKAO_KEY", "").strip()
if not KEY:
    sys.exit("KAKAO_KEY 환경변수가 필요합니다")

SEARCH = "https://dapi.kakao.com/v2/local/search/keyword.json"
HEAD = {"Authorization": "KakaoAK " + KEY}

# 이름 앞뒤에 붙는 법인 표기 — 검색에 방해가 된다
LEGAL = re.compile(r"(주식회사|㈜|\(주\)|사회복지법인|의료법인|재단법인|사단법인|비영리법인)")
# 흔한 꼬리말 — 떼어내면 고유한 부분만 남는다
TAIL = re.compile(
    r"(아동청소년발달|아동청소년|아동발달|언어심리발달|언어심리|심리언어|언어인지|언어청각|언어치료|"
    r"심리치료|심리상담|심리발달|발달지원|아동상담|놀이치료|감각통합|인지학습|발달|언어|심리|아동)?"
    r"(센터|의원|병원|클리닉|연구소|치료실|교실|학원|상담소|복지관)$"
)


def norm(s: str) -> str:
    """비교용 정규화 — 법인 표기·공백·기호를 없앤다"""
    s = LEGAL.sub("", s or "")
    s = re.sub(r"\(.*?\)", "", s)
    return re.sub(r"[\s\[\]·.\-,]", "", s)


def core(s: str) -> str:
    """꼬리말을 뗀 고유 부분. 너무 짧아지면 원래 이름을 쓴다"""
    n = norm(s)
    c = TAIL.sub("", n)
    return c if len(c) >= 2 else n


def sim(a: str, b: str) -> float:
    return SequenceMatcher(None, norm(a), norm(b)).ratio()


def digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def meters(lat1, lon1, lat2, lon2) -> float:
    """두 좌표 사이 거리(m). 짧은 거리라 평면 근사로 충분하다"""
    dlat = (lat2 - lat1) * 111_320
    dlon = (lon2 - lon1) * 111_320 * math.cos(math.radians(lat1))
    return math.hypot(dlat, dlon)


def road_key(addr: str) -> str:
    """'경기도 부천시 원미로 123, 2층' -> '원미로123'

    같은 건물인지만 본다. 층·호수는 기관마다 다르니 뗀다.
    """
    head = (addr or "").split(",")[0]
    m = re.search(r"([가-힣A-Za-z0-9]+(?:대?로|길))\s*(\d+(?:-\d+)?)", head)
    return f"{m.group(1)}{m.group(2)}" if m else ""


def sigungu_of(addr: str) -> str:
    """'경기도 성남시 분당구 ...' → '분당구' (없으면 '성남시')"""
    parts = (addr or "").split()
    gu = [p for p in parts[:4] if p.endswith(("시", "군", "구"))]
    return gu[-1] if gu else ""


def search(client: httpx.Client, query: str, *, x=None, y=None, radius=None) -> list[dict]:
    params = {"query": query, "size": 15}
    if x and y:
        params |= {"x": f"{x}", "y": f"{y}", "radius": radius or 700, "sort": "distance"}
    try:
        r = client.get(SEARCH, params=params, headers=HEAD, timeout=15)
        if r.status_code != 200:
            return []
        return r.json().get("documents", [])
    except Exception:
        return []


def judge(row: dict, doc: dict) -> tuple[str, float, float | None] | None:
    """후보 하나를 판정한다. 받아들이면 (근거, 점수), 아니면 None"""
    name = row["name"]
    cand = doc.get("place_name", "")
    addr = doc.get("road_address_name") or doc.get("address_name") or ""

    # 1) 전화번호가 같으면 끝
    def dist() -> float | None:
        try:
            return meters(float(row["lat"]), float(row["lon"]), float(doc["y"]), float(doc["x"]))
        except (TypeError, ValueError, KeyError):
            return None

    ours, theirs = digits(row.get("tel")), digits(doc.get("phone"))
    if ours and theirs and ours == theirs:
        return "TEL", sim(name, cand), dist()

    # 지역이 다르면 무조건 버린다 (동명 기관이 전국에 있다)
    our_gu = sigungu_of(row.get("address")) or row.get("sigungu", "")
    if our_gu and our_gu not in addr:
        return None

    s = sim(name, cand)

    # 2) 이름이 같거나 한쪽이 다른 쪽을 품는다
    a, b = norm(name), norm(cand)
    if a and b and (a == b or a in b or b in a) and len(min(a, b, key=len)) >= 3:
        return "NAME", s, dist()

    # 3) 도로명 주소의 건물이 같고 이름도 어느 정도 닮았다
    rk = road_key(row.get("address"))
    if rk and rk == road_key(addr) and s >= 0.55:
        return "ADDR", s, dist()

    # 4) 좌표가 가깝고 이름도 어느 정도 닮았다
    d = dist()
    if d is not None and d <= 300 and s >= 0.55:
        return "NEAR", s, d
    return None


def best_match(client: httpx.Client, row: dict) -> dict | None:
    """여러 검색 방식을 순서대로 시도해 가장 확실한 후보 하나를 고른다"""
    lat = row.get("lat") or ""
    lon = row.get("lon") or ""
    has_xy = bool(lat and lon)

    queries = []
    # 전화번호로 바로 찾는다 — 이름이 아무리 달라도 번호가 같으면 같은 곳이다
    if row.get("tel"):
        queries.append((row["tel"], {}))
    if has_xy:
        queries.append((row["name"], {"x": lon, "y": lat, "radius": 700}))
        if core(row["name"]) != norm(row["name"]):
            queries.append((core(row["name"]), {"x": lon, "y": lat, "radius": 700}))
        queries.append((row["name"], {"x": lon, "y": lat, "radius": 2000}))
    gu = sigungu_of(row.get("address")) or row.get("sigungu", "")
    if gu:
        queries.append((f"{gu} {row['name']}", {}))
    queries.append((row["name"], {}))
    # 주소로 그 건물의 업소를 훑는다 (도로명 주소가 있을 때만 뜻이 있다)
    if road_key(row.get("address")):
        queries.append((row["address"].split(",")[0], {}))

    rank = {"TEL": 3, "NAME": 2, "ADDR": 2, "NEAR": 1}
    best = None
    for query, opts in queries:
        for doc in search(client, query, **opts):
            got = judge(row, doc)
            if not got:
                continue
            why, score, dist = got
            key = (rank[why], score)
            if best is None or key > best[0]:
                best = (key, why, doc, score, dist)
            if why == "TEL":                 # 전화 일치보다 확실한 건 없다
                return {"why": why, "doc": doc, "sim": score, "dist": dist}
        if best and best[1] in ("NAME", "ADDR"):   # 이름·건물이 맞으면 더 볼 필요 없다
            break
    return {"why": best[1], "doc": best[2], "sim": best[3], "dist": best[4]} if best else None


def main() -> None:
    args = sys.argv[1:]
    if len(args) < 2:
        sys.exit(__doc__)
    src, dst = args[0], args[1]
    limit = next((int(a) for a in args if a.isdigit()), 10**9)
    resume = "--resume" in args
    rps = next((float(a.split("=", 1)[1]) for a in args if a.startswith("--rps=")), 4.0)
    gap = 1.0 / rps

    rows = list(csv.DictReader(io.open(src, encoding="utf-8-sig")))
    done: set[str] = set()
    if resume and os.path.exists(dst):
        done = {r["biz_no"] for r in csv.DictReader(io.open(dst, encoding="utf-8-sig"))}
        print(f"이어서 - 이미 끝난 {len(done):,}곳 건너뜀")

    todo = [r for r in rows if r["biz_no"] not in done][:limit]
    print(f"대상 {len(todo):,}곳, 초당 {rps}건")

    cols = ["biz_no", "place_url", "kakao_name", "kakao_addr", "kakao_tel", "kakao_x", "kakao_y",
            "why", "name_sim", "dist_m", "kakao_category"]
    new = not (resume and os.path.exists(dst))
    out = io.open(dst, "w" if new else "a", encoding="utf-8", newline="")
    w = csv.DictWriter(out, fieldnames=cols)
    if new:
        w.writeheader()

    client = httpx.Client(timeout=20)
    hit = 0
    fails = 0
    for i, row in enumerate(todo, 1):
        t0 = time.time()
        try:
            m = best_match(client, row)
            fails = 0
        except Exception as e:                       # 네트워크 흔들림은 넘어간다
            print(f"  ! {row['name']}: {e}")
            fails += 1
            if fails >= 10:
                print("연속 실패가 많아 멈춥니다"); break
            m = None

        rec = {c: "" for c in cols}
        rec["biz_no"] = row["biz_no"]
        if m:
            d = m["doc"]
            rec |= {
                "place_url": d.get("place_url", ""),
                "kakao_name": d.get("place_name", ""),
                "kakao_addr": d.get("road_address_name") or d.get("address_name") or "",
                "kakao_tel": d.get("phone", ""),
                "kakao_x": d.get("x", ""),
                "kakao_y": d.get("y", ""),
                "why": m["why"],
                "name_sim": f"{m['sim']:.2f}",
                "dist_m": "" if m["dist"] is None else f"{m['dist']:.0f}",
                "kakao_category": d.get("category_name", ""),
            }
            hit += 1
        w.writerow(rec)
        out.flush()

        if i % 50 == 0 or i == len(todo):
            print(f"  {i:,}/{len(todo):,}  찾음 {hit:,} ({hit/i*100:.0f}%)")
        time.sleep(max(0.0, gap - (time.time() - t0)))

    out.close()
    print(f"\n끝 — {hit:,}곳 새로 찾음 → {dst}")


if __name__ == "__main__":
    main()
