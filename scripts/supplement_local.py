# -*- coding: utf-8 -*-
"""지자체 공공데이터셋으로 전국 마스터 보완 (전화·주소·위경도·프로그램내용)"""
import csv, io, os, re, glob, collections

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
D = lambda *p: os.path.join(BASE, *p)

def norm(s):
    s = re.sub(r"\(.*?\)", "", s or "")
    s = re.sub(r"주식회사|사회적협동조합|사단법인|재단법인|의료법인|부설|㈜", "", s)
    return re.sub(r"[\s\[\]·\.\-,]", "", s)

def pick(hdr, *keys):
    for k in keys:
        for i, h in enumerate(hdr):
            if k in h.replace(" ", ""):
                return i
    return None

# 지자체 파일에서 (기관명 -> 정보) 인덱스 구축
local = {}
for p in sorted(glob.glob(D("data", "raw", "local", "*.csv"))):
    raw = open(p, "rb").read()
    txt = None
    for e in ("cp949", "euc-kr", "utf-8-sig", "utf-8"):
        try: txt = raw.decode(e); break
        except Exception: pass
    if not txt: continue
    rows = [r for r in csv.reader(io.StringIO(txt)) if any(c.strip() for c in r)]
    if len(rows) < 2: continue
    hdr = [c.strip() for c in rows[0]]
    i_nm  = pick(hdr, "제공기관명", "기관명", "시설명", "명칭")
    i_tel = pick(hdr, "전화번호", "연락처")
    i_ad  = pick(hdr, "도로명주소", "소재지도로명주소", "기관주소", "주소", "소재지")
    i_lat = pick(hdr, "위도"); i_lon = pick(hdr, "경도")
    i_pg  = pick(hdr, "프로그램내용", "서비스내용", "제공영역")
    if i_nm is None: continue
    for r in rows[1:]:
        if i_nm >= len(r) or not r[i_nm].strip(): continue
        k = norm(r[i_nm])
        d = local.setdefault(k, {})
        def put(key, idx):
            if idx is not None and idx < len(r) and r[idx].strip() and not d.get(key):
                d[key] = r[idx].strip()
        put("tel", i_tel); put("address", i_ad)
        put("lat", i_lat); put("lon", i_lon); put("programs", i_pg)

print("지자체 파일에서 %d개 기관 정보 인덱싱" % len(local))

rows = list(csv.DictReader(io.open(D("data", "nationwide_master.csv"), encoding="utf-8-sig")))
fields = list(rows[0].keys())
if "programs_local" not in fields: fields.append("programs_local")

stat = collections.Counter()
for r in rows:
    r.setdefault("programs_local", "")
    d = local.get(norm(r["name"]))
    if not d: continue
    stat["HIT"] += 1
    if not r.get("tel") and d.get("tel"):
        r["tel"] = re.sub(r"\s+", "", d["tel"]); stat["TEL"] += 1
    if not r.get("address") and d.get("address"):
        r["address"] = d["address"]; stat["ADDR"] += 1
    if not r.get("lat") and d.get("lat"):
        r["lat"], r["lon"] = d.get("lat", ""), d.get("lon", ""); stat["GEO"] += 1
    if d.get("programs"):
        r["programs_local"] = d["programs"]; stat["PROG"] += 1

with io.open(D("data", "nationwide_master.csv"), "w", encoding="utf-8-sig", newline="") as fp:
    w = csv.DictWriter(fp, fieldnames=fields); w.writeheader(); w.writerows(rows)

n = len(rows)
print("이름 일치 %d곳 → 전화 +%d · 주소 +%d · 좌표 +%d · 프로그램내용 +%d"
      % (stat["HIT"], stat["TEL"], stat["ADDR"], stat["GEO"], stat["PROG"]))
for lab, k in (("전화번호", "tel"), ("도로명주소", "address"), ("좌표", "lat"), ("프로그램내용", "programs_local")):
    c = sum(1 for r in rows if r.get(k))
    print("  %-12s %5d / %d  %5.1f%%" % (lab, c, n, 100.0 * c / n))
