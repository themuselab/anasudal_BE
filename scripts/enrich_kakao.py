# -*- coding: utf-8 -*-
"""카카오 로컬 API 보강 (주소 1차 검증 · 지역번호 2차 검증)

매칭 판정
  1차 주소 : 카카오 결과 주소에 공공 시군구가 포함되어야 함.
             공공 도로명주소가 있으면 도로명(예: '건강로')까지 일치해야 STRICT.
  2차 전화 : 지역번호가 해당 시도와 일치해야 함.
             010/070/1500번대 등 지역 무관 번호는 중립(통과).
             1차 통과 + 2차 불일치 -> 기관 정보는 채우되 전화번호만 버림.

사용: KAKAO_KEY=<REST키> python scripts/enrich_kakao.py [건수] [--reset] [--sido=강원특별자치도]
"""
import csv, io, os, re, json, subprocess, sys, time, collections, urllib.parse

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
D = lambda *p: os.path.join(BASE, *p)
KEY = os.environ.get("KAKAO_KEY", "").strip()
if not KEY:
    sys.exit("KAKAO_KEY 환경변수가 필요합니다")

args = sys.argv[1:]
RESET = "--reset" in args
SIDO = next((a.split("=", 1)[1] for a in args if a.startswith("--sido=")), "")
LIMIT = next((int(a) for a in args if a.isdigit()), 10**9)

AREA = {"서울특별시": "02", "부산광역시": "051", "대구광역시": "053", "인천광역시": "032",
        "광주광역시": "062", "대전광역시": "042", "울산광역시": "052", "세종특별자치시": "044",
        "경기도": "031", "강원특별자치도": "033", "충청북도": "043", "충청남도": "041",
        "전북특별자치도": "063", "전라남도": "061", "경상북도": "054", "경상남도": "055",
        "제주특별자치도": "064"}
NEUTRAL = ("010", "011", "016", "017", "018", "019", "070", "080", "15", "16", "18", "0507")

KAKAO_COLS = ("homepage", "own_homepage", "kakao_category", "match_conf")

def api(url):
    p = subprocess.run(["curl", "-s", "-m", "20", "-H", "Authorization: KakaoAK " + KEY, url],
                       capture_output=True)
    try:
        return json.loads(p.stdout.decode("utf-8", "replace"))
    except Exception:
        return {}

q = lambda s: urllib.parse.quote(s)

def norm(s):
    s = re.sub(r"\(.*?\)", "", s or "")
    return re.sub(r"[\s\[\]·\.\-,㈜]", "", s)

def road_of(addr):
    """주소에서 도로명 추출: '강원도 원주시 건강로25, 2층' -> '건강로'"""
    m = re.search(r"([가-힣A-Za-z]+(?:대?로|길))\s*\d", addr or "")
    return m.group(1) if m else ""

def area_ok(sido, phone):
    if not phone:
        return True                       # 전화 없음은 판정 보류
    d = re.sub(r"\D", "", phone)
    if any(d.startswith(p) for p in NEUTRAL):
        return True
    want = AREA.get(sido, "")
    return bool(want) and d.startswith(want)

def place_detail(pid):
    p = subprocess.run(["curl", "-s", "-m", "20",
                        "-A", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120",
                        "-H", "Accept: application/json",
                        "-H", "Origin: https://place.map.kakao.com",
                        "-H", "Referer: https://place.map.kakao.com/" + pid,
                        "-H", "pf: web",
                        "https://place-api.map.kakao.com/places/panel3/" + pid],
                       capture_output=True)
    try:
        s = json.loads(p.stdout.decode("utf-8", "replace")).get("summary", {})
    except Exception:
        return "", ""
    hp = next((u for u in (s.get("homepages") or [])
               if isinstance(u, str) and u.startswith("http") and "kakao" not in u), "")
    tel = next((t.get("tel") for t in (s.get("phone_numbers") or [])
                if isinstance(t, dict) and t.get("tel")), "")
    return hp, tel

rows = list(csv.DictReader(io.open(D("data", "nationwide_master.csv"), encoding="utf-8-sig")))
fields = list(rows[0].keys())
for c in KAKAO_COLS:
    if c not in fields:
        fields.append(c)
for r in rows:
    for c in fields:
        r.setdefault(c, "")

if RESET:
    for r in rows:
        for c in KAKAO_COLS:
            r[c] = ""
        if r.get("src", "").startswith("broso") and "ssis" not in r["src"]:
            r["tel"] = ""            # 카카오가 넣었던 전화 제거 (공공 결합분은 보존)
        r["lat"] = r["lon"] = ""
    print("기존 카카오 컬럼 초기화", flush=True)

targets = [r for r in rows if not r.get("match_conf")]
if SIDO:
    targets = [r for r in targets if r["sido"] == SIDO]
targets = targets[:LIMIT]
print("대상 %d곳" % len(targets), flush=True)

stat = collections.Counter()
for i, r in enumerate(targets, 1):
    gu = r["sigungu"].split()[-1] if r["sigungu"] else ""
    road = road_of(r["address"])
    docs = (api("https://dapi.kakao.com/v2/local/search/keyword.json?query=%s&size=15" % q(r["name"]))
            .get("documents") or [])
    if not docs:
        alt = re.sub(r"\(.*?\)|\s*\d+호점|\s*[가-힣]+점$", "", r["name"]).strip()
        if alt and alt != r["name"]:
            docs = (api("https://dapi.kakao.com/v2/local/search/keyword.json?query=%s&size=15" % q(alt))
                    .get("documents") or [])

    best, conf = None, ""
    for doc in docs:
        if norm(doc.get("place_name")) != norm(r["name"]):
            continue
        a = (doc.get("road_address_name") or "") + " " + (doc.get("address_name") or "")
        if gu and gu not in a:                    # ① 주소 1차 — 시군구 불일치는 즉시 탈락
            continue
        if road and road in a:                    # 도로명까지 일치
            best, conf = doc, "STRICT"; break
        if not best:
            best, conf = doc, "ADDR"
    if best and not area_ok(r["sido"], best.get("phone")):
        conf += "_TEL_MISMATCH"                   # ② 지역번호 2차 — 불일치 시 전화 폐기

    if not best:
        r["match_conf"] = "NONE"; stat["NO_MATCH"] += 1
    else:
        r["match_conf"] = conf
        stat[conf.split("_")[0]] += 1
        r["homepage"] = best.get("place_url", "")
        r["kakao_category"] = best.get("category_name", "")
        r["lat"], r["lon"] = best.get("y", ""), best.get("x", "")
        if "TEL_MISMATCH" in conf:
            stat["TEL_DROP"] += 1
        elif best.get("phone") and not r.get("tel"):
            r["tel"] = best["phone"]; stat["TEL"] += 1
        pid = re.search(r"/(\d+)$", best.get("place_url", ""))
        if pid:
            hp, tel2 = place_detail(pid.group(1))
            if hp:
                r["own_homepage"] = hp; stat["OWN_HP"] += 1
            if tel2 and not r.get("tel") and area_ok(r["sido"], tel2):
                r["tel"] = tel2; stat["TEL"] += 1
    if i % 100 == 0:
        print("  %d/%d  STRICT %d · ADDR %d · 미매칭 %d"
              % (i, len(targets), stat["STRICT"], stat["ADDR"], stat["NO_MATCH"]), flush=True)
    time.sleep(0.05)

with io.open(D("data", "nationwide_master.csv"), "w", encoding="utf-8-sig", newline="") as fp:
    w = csv.DictWriter(fp, fieldnames=fields); w.writeheader(); w.writerows(rows)

n = len(targets)
print("\n=== 이번 실행 %d곳 ===" % n)
print("  STRICT(이름+시군구+도로명) : %d (%.0f%%)" % (stat["STRICT"], 100.0*stat["STRICT"]/max(n,1)))
print("  ADDR  (이름+시군구)        : %d (%.0f%%)" % (stat["ADDR"], 100.0*stat["ADDR"]/max(n,1)))
print("  미매칭                     : %d (%.0f%%)" % (stat["NO_MATCH"], 100.0*stat["NO_MATCH"]/max(n,1)))
print("  지역번호 불일치로 전화 폐기 : %d" % stat["TEL_DROP"])
print("  자체 홈페이지 확보          : %d" % stat["OWN_HP"])
