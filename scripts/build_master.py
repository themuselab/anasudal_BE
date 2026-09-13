# -*- coding: utf-8 -*-
"""서울 발달재활 기관 마스터 목록 = NISE(전화O) + 복지부 CSV(교차검증) + 서울아이 협약(홈페이지O)"""
import csv, io, os, re, collections

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
D = lambda *p: os.path.join(BASE, *p)

def norm_name(s):
    return re.sub(r"[\s()\[\]㈜\(주\)·\.]", "", s or "")
def digits(s):
    return re.sub(r"\D", "", s or "")

nise = list(csv.DictReader(io.open(D("data","seoul_agencies_nise.csv"), encoding="utf-8-sig")))

raw = open(D("data","raw","mohw.csv"), "rb").read()
for enc in ("cp949","euc-kr","utf-8"):
    try: mo_txt = raw.decode(enc); break
    except Exception: pass
mohw = [r for r in csv.DictReader(io.StringIO(mo_txt)) if "서울" in r["시도"]]

seouli = list(csv.DictReader(io.open(D("data","seouli_clinics.csv"), encoding="utf-8-sig")))

master = {}
for r in nise:
    master[norm_name(r["name"])] = {
        "name": r["name"], "sigungu": r["sigungu"], "address": r["address"], "tel": r["tel"],
        "in_nise": "Y", "in_mohw": "", "in_seouli": "", "homepage": "",
    }

matched_mohw = 0
for r in mohw:
    k = norm_name(r["제공 기관명"])
    if k in master:
        master[k]["in_mohw"] = "Y"; matched_mohw += 1
    else:
        master[k] = {"name": r["제공 기관명"].strip(), "sigungu": r["시군구"].strip(),
                     "address": r["주소"].strip(), "tel": "",
                     "in_nise": "", "in_mohw": "Y", "in_seouli": "", "homepage": ""}

tel_index = {digits(v["tel"]): k for k, v in master.items() if digits(v["tel"])}
matched_seouli = 0
for r in seouli:
    k = norm_name(r["name"])
    if k not in master and digits(r["tel"]) in tel_index:
        k = tel_index[digits(r["tel"])]
    if k in master:
        master[k]["in_seouli"] = "Y"; master[k]["homepage"] = r["homepage"]; matched_seouli += 1

rows = sorted(master.values(), key=lambda r: (r["sigungu"], r["name"]))
out = D("data","seoul_master.csv")
with io.open(out, "w", encoding="utf-8-sig", newline="") as fp:
    w = csv.DictWriter(fp, fieldnames=list(rows[0].keys()))
    w.writeheader(); w.writerows(rows)

o = io.open(D("data","master_report.txt"), "w", encoding="utf-8")
w = lambda *a: o.write(" ".join(str(x) for x in a) + "\n")
w("서울 발달재활 기관 마스터 목록")
w("")
w("  NISE(온맘)          : %d건  (전화번호 보유)" % len(nise))
w("  보건복지부 CSV      : %d건" % len(mohw))
w("  서울아이 협약기관   : %d건  (홈페이지 URL 보유)" % len(seouli))
w("")
w("  병합 후 고유 기관   : %d건" % len(rows))
w("  두 공공소스 모두 등재: %d건 (교차검증됨)" % matched_mohw)
w("  홈페이지 URL 확보   : %d건 (%.0f%%)" % (matched_seouli, 100.0*matched_seouli/len(rows)))
w("")
c = collections.Counter((r["in_nise"], r["in_mohw"]) for r in rows)
w("  출처 조합: NISE만 %d / 복지부만 %d / 양쪽 %d"
  % (c[("Y","")], c[("","Y")], c[("Y","Y")]))
w("")
w("=== A-2 필드 현재 충족률 (마스터 %d건 기준) ===" % len(rows))
w("  기관명·주소       100%")
w("  전화번호           %.0f%%" % (100.0*sum(1 for r in rows if r["tel"])/len(rows)))
w("  홈페이지(태깅 입력) %.0f%%" % (100.0*matched_seouli/len(rows)))
w("  치료영역             0%   <- 공공 소스 전무")
w("  연령대/중증도/비용/대기/운영시간/치료사  0%   <- 공공 소스 전무")
o.close()
