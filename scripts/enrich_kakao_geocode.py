# -*- coding: utf-8 -*-
"""카카오 로컬 API(공식)로 좌표·전화·카카오맵링크 보강.

enrich_kakao.py 와 무엇이 다른가
  · enrich_kakao.py 는 **기관명 키워드 검색**으로 매칭한다. 이름이 공공데이터와
    카카오에서 다르면 통째로 실패한다(match_conf=NONE, 990곳).
  · 이 스크립트는 **주소 검색**을 먼저 쓴다. 이름이 달라도 주소만 맞으면 좌표가 나온다.
    그래서 앞 스크립트가 놓친 곳을 건진다.

카카오 공식 REST API 가 주는 것 / 안 주는 것
  줌   : 좌표(x,y) · 전화번호 · 카카오맵 place_url · 카테고리
  안 줌: **운영시간**, **기관 자체 홈페이지**
         → 이 둘은 공공데이터포털 쪽에서 받아야 한다. 여기서는 건드리지 않는다.

입력 : CSV (biz_no,name,address,sido,sigungu,tel,place_url,lat,lon)
출력 : CSV (biz_no,lat,lon,tel,place_url,method,query)  — 채운 것만

사용:
  KAKAO_KEY=<REST키> python scripts/enrich_kakao_geocode.py 입력.csv 출력.csv [건수]
"""
import csv
import io
import os
import re
import sys
import time

import httpx

KEY = os.environ.get("KAKAO_KEY", "").strip()
if not KEY:
    sys.exit("KAKAO_KEY 환경변수가 필요합니다 (카카오 REST 키)")

ADDR_URL = "https://dapi.kakao.com/v2/local/search/address.json"
KW_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"
HEAD = {"Authorization": "KakaoAK " + KEY}

# 시도 이름이 바뀐 것들 — 공공데이터는 옛 이름을 쓰는 경우가 많다
SIDO_ALIAS = {
    "강원도": "강원특별자치도",
    "전라북도": "전북특별자치도",
}
# 지역번호 검증용 (잘못된 전화번호를 채우지 않기 위해)
AREA = {"서울특별시": "02", "부산광역시": "051", "대구광역시": "053", "인천광역시": "032",
        "광주광역시": "062", "대전광역시": "042", "울산광역시": "052", "세종특별자치시": "044",
        "경기도": "031", "강원특별자치도": "033", "충청북도": "043", "충청남도": "041",
        "전북특별자치도": "063", "전라남도": "061", "경상북도": "054", "경상남도": "055",
        "제주특별자치도": "064"}
NEUTRAL = ("010", "011", "016", "017", "018", "019", "070", "080", "15", "16", "18", "0507")

client = httpx.Client(headers=HEAD, timeout=20)


def api(url, query, extra=None):
    """429(한도 초과)면 물러섰다 다시. 그 외 오류는 빈 결과로 넘긴다."""
    params = {"query": query, "size": 10}
    if extra:
        params.update(extra)
    for attempt in range(4):
        try:
            r = client.get(url, params=params)
        except Exception:
            time.sleep(1 + attempt)
            continue
        if r.status_code == 429:
            time.sleep(2 ** attempt)
            continue
        if r.status_code != 200:
            return []
        return r.json().get("documents") or []
    return []


def clean_address(addr, sido, sigungu):
    """'강원도 강릉시 곶감전길 15(성남동)2~3층' -> '강원특별자치도 강릉시 곶감전길 15'

    카카오 주소검색은 층·호·건물명이 붙으면 못 찾는 경우가 많다.
    도로명+건물번호까지만 남긴다.
    """
    if not addr:
        return ""
    a = re.sub(r"\([^)]*\)", " ", addr)          # (성남동), (홍제동, 이스턴빌딩)
    a = re.sub(r"[,·]", " ", a)
    # 호수·층이 건물번호에 들러붙는 것을 먼저 뗀다.
    #   '남악3로 80404호' 는 '남악3로 80' + '404호' 다. 안 떼면 건물번호가 80404 가 된다.
    a = re.sub(r"(\d)(\d{3})\s*호\b", r"\1", a)   # 80404호 -> 80
    a = re.sub(r"\s*\d+\s*호\b", " ", a)          # 남은 '310호'
    a = re.sub(r"\s*(?:지하\s*)?[B]?\d+\s*층\b", " ", a)
    a = re.sub(r"(\d+)\s*번지", r"\1", a)         # '구미동 23번지' -> '구미동 23'
    a = re.sub(r"\s+", " ", a).strip()
    for old, new in SIDO_ALIAS.items():
        if a.startswith(old):
            a = new + a[len(old):]

    # 도로명 + 건물번호를 부분으로 잡아 다시 조립한다.
    #   도로명 토큰은 숫자를 포함할 수 있고('심반동3로') 'N번길'이 뒤에 붙을 수 있다('회산로351번길').
    #   앞에서 통째로 자르면 '회산로 351' 처럼 번길이 날아가 엉뚱한 주소가 된다.
    m = re.search(r"([가-힣A-Za-z0-9]+(?:대?로|길))\s*(\d+번길)?\s*(\d+(?:-\d+)?)", a)
    if m:
        head = a[:m.start()].strip()                 # 시도 시군구
        road = m.group(1)
        beon = m.group(2) or ""                      # '351번길'
        num = m.group(3)
        return re.sub(r"\s+", " ", f"{head} {road}{beon} {num}").strip()

    # 지번 주소: '... 읍/면/동 123-4'
    m = re.search(r"^(.*?[읍면동리])\s*(\d+(?:-\d+)?)", a)
    if m:
        return re.sub(r"\s+", " ", f"{m.group(1)} {m.group(2)}").strip()

    return a


def area_ok(sido, phone):
    if not phone:
        return False
    d = re.sub(r"\D", "", phone)
    if any(d.startswith(p) for p in NEUTRAL):
        return True
    want = AREA.get(SIDO_ALIAS.get(sido, sido), "")
    return bool(want) and d.startswith(want)


def norm_name(s):
    s = re.sub(r"\([^)]*\)", "", s or "")
    s = re.sub(r"(사|주|재)\)", "", s)                       # 사)담장너머 -> 담장너머
    s = re.sub(r"[\s\[\]·.\-,;㈜]", "", s)
    return re.sub(r"(주식회사|사단법인|재단법인|사회적협동조합|부설)", "", s)


def names_match(a, b):
    """'파랑새감각통합언어발달' 과 '파랑새감각통합언어발달센터' 는 같은 곳으로 본다.

    완전 일치만 요구하면 '센터/점' 같은 접미사 차이로 통째로 놓친다.
    다만 짧은 이름의 포함 관계는 오탐이 크므로 6자 이상일 때만 인정한다.
    (시군구 일치는 호출부에서 이미 확인한다)
    """
    x, y = norm_name(a), norm_name(b)
    if not x or not y:
        return False
    if x == y:
        return True
    short, long_ = (x, y) if len(x) <= len(y) else (y, x)
    return len(short) >= 6 and short in long_


def _addr_try(query):
    docs = api(ADDR_URL, query)
    return (docs[0]["y"], docs[0]["x"]) if docs else None


def geocode(row):
    """좌표를 찾는다. (lat, lon, method, query) 또는 None

    method 로 정확도를 구분한다.
      ADDR / ADDR2 / KEYWORD : 번지까지 맞은 정확한 좌표
      ROAD                   : 건물번호를 못 찾아 도로·동 중심점으로 대체 (수백 m 오차)
    """
    sido, sigungu = row.get("sido", ""), row.get("sigungu", "")
    name = row.get("name", "")
    gu = sigungu.split()[-1] if sigungu else ""
    cleaned = clean_address(row.get("address", ""), sido, sigungu)

    # ① 정리한 주소 그대로
    if cleaned:
        hit = _addr_try(cleaned)
        if hit:
            return hit[0], hit[1], "ADDR", cleaned

    # ② 시군구를 앞에 붙여 다시 (시도 표기가 다른 경우 대비)
    if cleaned and gu and gu not in cleaned:
        alt = f"{gu} {cleaned}"
        hit = _addr_try(alt)
        if hit:
            return hit[0], hit[1], "ADDR2", alt

    # ③ 이름 + 시군구 키워드 검색
    if name:
        for d in api(KW_URL, f"{gu} {name}".strip()):
            a = (d.get("road_address_name") or "") + " " + (d.get("address_name") or "")
            if gu and gu not in a:
                continue                      # 다른 시군구면 버린다
            if not names_match(d.get("place_name"), name):
                continue
            return d["y"], d["x"], "KEYWORD", f"{gu} {name}"

    # ④ 건물번호를 떼고 도로·동 중심점 (정확도가 떨어지므로 ROAD 로 표시)
    if cleaned and " " in cleaned:
        road_only = cleaned.rsplit(" ", 1)[0]
        if len(road_only) > len(gu) + 2:
            hit = _addr_try(road_only)
            if hit:
                return hit[0], hit[1], "ROAD", road_only
    return None


def place_info(row):
    """전화·카카오맵 링크. 이름과 시군구가 모두 맞을 때만 채운다."""
    name, sigungu = row.get("name", ""), row.get("sigungu", "")
    gu = sigungu.split()[-1] if sigungu else ""
    if not name:
        return "", ""
    for d in api(KW_URL, f"{gu} {name}".strip()):
        a = (d.get("road_address_name") or "") + " " + (d.get("address_name") or "")
        if gu and gu not in a:
            continue
        if not names_match(d.get("place_name"), name):
            continue
        tel = d.get("phone") or ""
        if tel and not area_ok(row.get("sido", ""), tel):
            tel = ""                          # 지역번호가 안 맞으면 버린다
        return tel, d.get("place_url") or ""
    return "", ""


def main():
    src, dst = sys.argv[1], sys.argv[2]
    limit = int(sys.argv[3]) if len(sys.argv) > 3 else 10 ** 9

    rows = list(csv.DictReader(io.open(src, encoding="utf-8-sig")))[:limit]
    print(f"대상 {len(rows)}곳", flush=True)

    out = []
    stat = {"ADDR": 0, "ADDR2": 0, "KEYWORD": 0, "ROAD": 0, "NONE": 0, "TEL": 0, "URL": 0}

    for i, r in enumerate(rows, 1):
        lat = lon = method = query = ""
        if not (r.get("lat") or "").strip():
            g = geocode(r)
            if g:
                lat, lon, method, query = g
                stat[method] += 1
            else:
                method = "NONE"
                stat["NONE"] += 1

        tel = url = ""
        need_tel = not (r.get("tel") or "").strip()
        need_url = not (r.get("place_url") or "").strip()
        if need_tel or need_url:
            t, u = place_info(r)
            if need_tel and t:
                tel = t
                stat["TEL"] += 1
            if need_url and u:
                url = u
                stat["URL"] += 1

        if lat or tel or url:
            out.append({"biz_no": r["biz_no"], "lat": lat, "lon": lon,
                        "tel": tel, "place_url": url, "method": method, "query": query})

        if i % 50 == 0:
            print(f"  {i}/{len(rows)}  좌표 {stat['ADDR']+stat['ADDR2']+stat['KEYWORD']+stat['ROAD']}"
                  f" · 실패 {stat['NONE']} · 전화 {stat['TEL']} · 링크 {stat['URL']}", flush=True)
        time.sleep(0.03)

    with io.open(dst, "w", encoding="utf-8-sig", newline="") as fp:
        w = csv.DictWriter(fp, fieldnames=["biz_no", "lat", "lon", "tel", "place_url", "method", "query"])
        w.writeheader()
        w.writerows(out)

    exact = stat["ADDR"] + stat["ADDR2"] + stat["KEYWORD"]
    got = exact + stat["ROAD"]
    tried = got + stat["NONE"]
    print(f"\n=== 결과 ===")
    print(f"  좌표 시도 {tried}곳 → 성공 {got} ({100.0*got/max(tried,1):.0f}%)")
    print(f"    정확 {exact}  (주소 {stat['ADDR']} · 시군구보정 {stat['ADDR2']} · 이름 {stat['KEYWORD']})")
    print(f"    근사 {stat['ROAD']}  (도로·동 중심점, 수백 m 오차)")
    print(f"  전화 {stat['TEL']}건 · 카카오맵 링크 {stat['URL']}건")
    print(f"  파일: {dst} ({len(out)}행)")


if __name__ == "__main__":
    main()
