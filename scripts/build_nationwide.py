# -*- coding: utf-8 -*-
"""전국 발달재활 기관 마스터 빌드
  기준(base) : broso 2026 가격공시  -> 치료영역·단가·사업자등록번호
  + 보건복지부 제공기관 현황        -> 도로명주소
  + 사회보장정보원 API             -> 전화·이메일 (있을 때)
  + NISE/지오코딩(서울)            -> 전화·위경도
공공에 없는 필드는 빈칸(null)으로 남긴다.
"""
import csv, io, os, re, collections

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
D = lambda *p: os.path.join(BASE, *p)

def norm(s):
    s = re.sub(r"\(.*?\)", "", s or "")
    s = re.sub(r"주식회사|사회적협동조합|사단법인|재단법인|의료법인|부설|㈜", "", s)
    return re.sub(r"[\s\[\]·\.\-,]", "", s)

def gu(s):
    return re.sub(r"^(서울특별시|부산광역시|대구광역시|인천광역시|광주광역시|대전광역시|울산광역시|"
                  r"세종특별자치시|경기도|강원특별자치도|충청북도|충청남도|전북특별자치도|전라남도|"
                  r"경상북도|경상남도|제주특별자치도)\s*", "", (s or "").strip())

def load(p, enc="utf-8-sig"):
    return list(csv.DictReader(io.open(p, encoding=enc)))

# 1) base = broso
base = load(D("data", "broso_nationwide.csv"))

# 2) 복지부 CSV -> 주소
raw = open(D("data", "raw", "mohw.csv"), "rb").read()
for e in ("cp949", "euc-kr", "utf-8"):
    try: mo_txt = raw.decode(e); break
    except Exception: pass
mohw = list(csv.DictReader(io.StringIO(mo_txt)))
mo_idx = {}
for r in mohw:
    mo_idx.setdefault((norm(r["제공 기관명"]), gu(r["시군구"])), r)
    mo_idx.setdefault(norm(r["제공 기관명"]), r)

# 3) 사회보장정보원 (있으면)
ss_tel, ss_mail = {}, {}
p_ss = D("data", "ssis_dev_rehab.csv")
if os.path.exists(p_ss):
    for r in load(p_ss):
        k = norm(r["providerName"])
        if r.get("telNumber"): ss_tel.setdefault(k, r["telNumber"])
        if r.get("email"):     ss_mail.setdefault(k, r["email"])

# 4) 서울 실측(NISE 전화 + 지오코딩)
seoul_tel, seoul_geo = {}, {}
for r in load(D("data", "seoul_agencies_geocoded.csv")):
    k = norm(r["name"])
    if r["tel"]: seoul_tel[k] = r["tel"]
    if r["lat"]: seoul_geo[k] = (r["lat"], r["lon"])

out = []
hit_addr = hit_tel = hit_geo = hit_mail = 0
for b in base:
    k = norm(b["name"]); g = gu(b["sigungu"])
    mo = mo_idx.get((k, g)) or mo_idx.get(k)
    addr = (mo["주소"].strip() if mo else "")
    tel  = seoul_tel.get(k) or ss_tel.get(k, "")
    lat, lon = seoul_geo.get(k, ("", ""))
    mail = ss_mail.get(k, "")
    if addr: hit_addr += 1
    if tel:  hit_tel += 1
    if lat:  hit_geo += 1
    if mail: hit_mail += 1
    out.append({
        "biz_no": b["biz_no"], "name": b["name"], "sido": b["sido"], "sigungu": b["sigungu"],
        "address": addr, "tel": tel, "email": mail, "lat": lat, "lon": lon,
        "areas": b["areas"], "area_count": b["area_count"],
        "price_min": b["price_min"], "price_max": b["price_max"], "visit": b["visit"],
        # 공공에 없음 → null 고정
        "specialty_extra": "", "operating_hours": "", "waiting": "",
        "severity": "", "age_range": "", "therapist_count": "", "homepage": "",
        "src": "broso" + ("+mohw" if mo else "") + ("+ssis" if (tel or mail) else ""),
    })

out.sort(key=lambda r: (r["sido"], r["sigungu"], r["name"]))
with io.open(D("data", "nationwide_master.csv"), "w", encoding="utf-8-sig", newline="") as fp:
    w = csv.DictWriter(fp, fieldnames=list(out[0].keys())); w.writeheader(); w.writerows(out)

n = len(out)
o = io.open(D("data", "nationwide_report.txt"), "w", encoding="utf-8"); w = lambda *a: o.write(" ".join(str(z) for z in a) + "\n")
w("전국 발달재활 기관 마스터 : %d곳 / %d개 시도" % (n, len({r["sido"] for r in out if r["sido"]})))
w("")
w("── 항상 채워짐 ──")
for lab, key in (("기관명", "name"), ("사업자등록번호", "biz_no"), ("시도·시군구", "sigungu"),
                 ("치료영역", "areas"), ("회기당 단가", "price_min")):
    c = sum(1 for r in out if r[key]); w("   %-14s %5d / %d  %5.1f%%" % (lab, c, n, 100.0 * c / n))
w("")
w("── 조인으로 채워짐 ──")
for lab, key in (("도로명주소", "address"), ("전화번호", "tel"), ("이메일", "email"),
                 ("위경도", "lat"), ("방문서비스", "visit")):
    c = sum(1 for r in out if r[key]); w("   %-14s %5d / %d  %5.1f%%" % (lab, c, n, 100.0 * c / n))
w("")
w("── 항상 null (공공에 없음) ──")
w("   specialty_extra · operating_hours · waiting · severity · age_range · therapist_count · homepage")
w("")
w("=== 시도별 (주소 결합률) ===")
bys = collections.defaultdict(lambda: [0, 0])
for r in out:
    bys[r["sido"]][0] += 1
    if r["address"]: bys[r["sido"]][1] += 1
for k, (t, a) in sorted(bys.items(), key=lambda x: -x[1][0]):
    w("   %-12s %4d곳  주소 %3.0f%%" % (k or "(미표기)", t, 100.0 * a / t))
o.close()
print("ok")
