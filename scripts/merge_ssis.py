# -*- coding: utf-8 -*-
"""사회보장정보원 수집분으로 전화·이메일·주소 보완"""
import csv, io, os, re, collections
BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
D = lambda *p: os.path.join(BASE, *p)
AREA = {"서울특별시":"02","부산광역시":"051","대구광역시":"053","인천광역시":"032","광주광역시":"062",
        "대전광역시":"042","울산광역시":"052","세종특별자치시":"044","경기도":"031","강원특별자치도":"033",
        "충청북도":"043","충청남도":"041","전북특별자치도":"063","전라남도":"061","경상북도":"054",
        "경상남도":"055","제주특별자치도":"064"}
NEUTRAL = ("010","011","016","017","018","019","070","080","15","16","18","0507")

def norm(s):
    s = re.sub(r"\(.*?\)", "", s or "")
    s = re.sub(r"주식회사|사회적협동조합|사단법인|재단법인|의료법인|부설|㈜", "", s)
    return re.sub(r"[\s\[\]·\.\-,]", "", s)

def area_ok(sido, phone):
    d = re.sub(r"\D", "", phone or "")
    if not d: return False
    if any(d.startswith(p) for p in NEUTRAL): return True
    want = AREA.get(sido, "")
    return bool(want) and d.startswith(want)

ss = collections.defaultdict(list)
for r in csv.DictReader(io.open(D("data", "ssis_dev_rehab.csv"), encoding="utf-8-sig")):
    ss[norm(r["providerName"])].append(r)

rows = list(csv.DictReader(io.open(D("data", "nationwide_master.csv"), encoding="utf-8-sig")))
fields = list(rows[0].keys())
stat = collections.Counter()
for r in rows:
    cands = ss.get(norm(r["name"]))
    if not cands: continue
    gu = r["sigungu"].split()[-1] if r["sigungu"] else ""
    # 같은 시도(가능하면 시군구)인 레코드 우선
    best = next((c for c in cands if gu and gu in (c.get("signguName") or "")), None) \
        or next((c for c in cands if r["sido"][:2] in (c.get("sidoName") or "")), None)
    if not best: continue
    stat["HIT"] += 1
    if not r.get("tel") and area_ok(r["sido"], best.get("telNumber")):
        r["tel"] = best["telNumber"]; stat["TEL"] += 1
    if not r.get("email") and best.get("email"):
        r["email"] = best["email"]; stat["MAIL"] += 1
    if not r.get("address") and best.get("loadAddress"):
        r["address"] = (best["loadAddress"] + " " + best.get("loadAddressDetail", "")).strip()
        stat["ADDR"] += 1

with io.open(D("data", "nationwide_master.csv"), "w", encoding="utf-8-sig", newline="") as fp:
    w = csv.DictWriter(fp, fieldnames=fields); w.writeheader(); w.writerows(rows)
n = len(rows)
print("지역검증 매칭 %d곳 → 전화 +%d · 이메일 +%d · 주소 +%d"
      % (stat["HIT"], stat["TEL"], stat["MAIL"], stat["ADDR"]))
for lab, k in (("전화번호","tel"),("이메일","email"),("도로명주소","address")):
    c = sum(1 for r in rows if r.get(k)); print("  %-10s %5d / %d  %5.1f%%" % (lab, c, n, 100.0*c/n))
