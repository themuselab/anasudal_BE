# -*- coding: utf-8 -*-
"""FAIL 건만 주소 정규화를 고쳐 재지오코딩. 버그: '헌릉로570길30' -> '헌릉로 570길30'(오) / '헌릉로570길 30'(정)"""
import csv, io, os, re, json, time, html, urllib.parse, subprocess

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
F = os.path.join(BASE, "data", "seoul_agencies_geocoded.csv")
UA = "hackathon-dev-rehab-matching/1.0 (victory.jun01@gmail.com)"

def normalize(addr):
    a = html.unescape(addr or "")
    a = re.sub(r"<!\[CDATA\[|\]\]>", " ", a)
    a = re.sub(r"\(.*?\)", " ", a)
    a = re.sub(r"\d+층.*$", "", a)
    a = re.sub(r",\s*[\dA-Za-z\-]+호.*$", "", a)
    a = re.sub(r"^서울시", "서울특별시", a)
    if not a.startswith("서울"):
        a = "서울특별시 " + a
    a = re.sub(r",.*$", "", a)
    a = re.sub(r"([가-힣]+로\d+번?길)\s*(\d)", r"\1 \2", a)   # 로N길M -> 로N길 M  (먼저)
    a = re.sub(r"([가-힣]+(?:로|길))\s*(\d)", r"\1 \2", a)     # 로M / 길M -> 로 M
    a = re.sub(r"([가-힣]+로)\s+(\d+번?길)", r"\1\2", a)       # 되돌림: 로 N길 -> 로N길
    return re.sub(r"\s+", " ", a).strip()

def q(url):
    r = subprocess.run(["curl", "-s", "-m", "25", "-A", UA, url], capture_output=True)
    try: return json.loads(r.stdout.decode("utf-8", "replace"))
    except Exception: return []

rows = list(csv.DictReader(io.open(F, encoding="utf-8-sig")))
targets = [r for r in rows if not r["lat"]]
print("재시도 대상 %d건" % len(targets), flush=True)

fixed = 0
for i, r in enumerate(targets, 1):
    norm = normalize(r["address"])
    for attempt, query in enumerate([norm, re.sub(r"\s+\d+$", "", norm)]):
        res = q("https://nominatim.openstreetmap.org/search?q=%s&format=json&limit=1&countrycodes=kr"
                % urllib.parse.quote(query))
        time.sleep(1.1)
        if res:
            lat, lon = float(res[0]["lat"]), float(res[0]["lon"])
            if 37.42 <= lat <= 37.70 and 126.76 <= lon <= 127.19:   # 서울 경계 검증
                r["lat"], r["lon"] = res[0]["lat"], res[0]["lon"]
                r["geo_precision"] = "EXACT_RETRY" if attempt == 0 else "STREET_RETRY"
                r["addr_norm"] = norm
                fixed += 1
                break
    if i % 25 == 0:
        print("  %d/%d  fixed=%d" % (i, len(targets), fixed), flush=True)

with io.open(F, "w", encoding="utf-8-sig", newline="") as fp:
    w = csv.DictWriter(fp, fieldnames=list(rows[0].keys()))
    w.writeheader(); w.writerows(rows)

got = sum(1 for r in rows if r["lat"])
print("DONE 재시도로 %d건 추가 -> 최종 %d/%d (%.1f%%)" % (fixed, got, len(rows), 100.0*got/len(rows)))
