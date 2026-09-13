# -*- coding: utf-8 -*-
"""NISE 서울 기관 주소 -> 위경도 (OSM Nominatim, 무키). 1req/sec 준수."""
import csv, io, os, re, json, time, urllib.parse, subprocess

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
IN  = os.path.join(BASE, "data", "seoul_agencies_nise.csv")
OUT = os.path.join(BASE, "data", "seoul_agencies_geocoded.csv")
UA  = "hackathon-dev-rehab-matching/1.0 (victory.jun01@gmail.com)"

def normalize(addr):
    a = addr.strip()
    a = re.sub(r'\(.*?\)', ' ', a)                 # (세곡동, 강남리더스프라자) 제거
    a = re.sub(r'\d+층.*$', '', a)                  # 층/호 제거
    a = re.sub(r',\s*[\d\-]+호.*$', '', a)
    a = re.sub(r'^서울시', '서울특별시', a)
    if not a.startswith('서울'):
        a = '서울특별시 ' + a
    a = re.sub(r'([가-힣]로|[가-힣]길|[가-힣]로\d+길)(\d)', r'\1 \2', a)  # 헌릉로569 -> 헌릉로 569
    a = re.sub(r',.*$', '', a)
    return re.sub(r'\s+', ' ', a).strip()

def q(url):
    # 이 환경의 python은 구형 TLS 협상 실패가 있어 curl로 우회
    r = subprocess.run(["curl", "-s", "-m", "25", "-A", UA, url],
                       capture_output=True)
    try:
        return json.loads(r.stdout.decode("utf-8", "replace"))
    except Exception:
        return []

rows = list(csv.DictReader(io.open(IN, encoding="utf-8-sig")))
out, hit = [], 0
for i, r in enumerate(rows, 1):
    norm = normalize(r["address"])
    lat = lon = ""; prec = "FAIL"
    for attempt, query in enumerate([norm, re.sub(r'\s+\d+$', '', norm)]):
        url = ("https://nominatim.openstreetmap.org/search?q=%s&format=json&limit=1&countrycodes=kr"
               % urllib.parse.quote(query))
        res = q(url)
        time.sleep(1.1)
        if res:
            lat, lon = res[0]["lat"], res[0]["lon"]
            prec = "EXACT" if attempt == 0 else "STREET"
            hit += 1
            break
    r2 = dict(r); r2.update({"addr_norm": norm, "lat": lat, "lon": lon, "geo_precision": prec})
    out.append(r2)
    if i % 25 == 0:
        print("  %d/%d  hit=%d" % (i, len(rows), hit), flush=True)

with io.open(OUT, "w", encoding="utf-8-sig", newline="") as fp:
    w = csv.DictWriter(fp, fieldnames=list(out[0].keys()))
    w.writeheader(); w.writerows(out)
print("DONE %d/%d geocoded (%.1f%%) -> %s" % (hit, len(rows), 100.0*hit/len(rows), OUT))
