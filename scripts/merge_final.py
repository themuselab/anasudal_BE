# -*- coding: utf-8 -*-
"""최종 병합: 마스터(NISE+복지부) + broso 가격공시 + 지오코딩"""
import csv, io, os, re, collections
BASE=os.path.join(os.path.dirname(os.path.abspath(__file__)),"..")
D=lambda *p: os.path.join(BASE,*p)
def norm(s): return re.sub(r"[\s()\[\]㈜·\.\-]|주식회사|사회적협동조합|부설","",s or "")

master=list(csv.DictReader(io.open(D("data","seoul_master.csv"),encoding="utf-8-sig")))
price=list(csv.DictReader(io.open(D("data","seoul_broso_price.csv"),encoding="utf-8-sig")))
geo={norm(r["name"]):r for r in csv.DictReader(io.open(D("data","seoul_agencies_geocoded.csv"),encoding="utf-8-sig")) if r["lat"]}

pidx={}
for p in price: pidx.setdefault(norm(p["name"]),p)

rows=[]; matched=0
for m in master:
    k=norm(m["name"]); p=pidx.get(k)
    if not p:  # 부분일치 재시도
        for pk,pv in pidx.items():
            if len(k)>=6 and (k in pk or pk in k): p=pv; break
    if p: matched+=1
    g=geo.get(k,{})
    rows.append({
        "name":m["name"],"sigungu":m["sigungu"],"address":m["address"],"tel":m["tel"],
        "lat":g.get("lat",""),"lon":g.get("lon",""),
        "biz_no":p["biz_no"] if p else "", "areas":p["areas"] if p else "",
        "area_count":p["area_count"] if p else "",
        "price_min":p["price_min"] if p else "", "price_max":p["price_max"] if p else "",
        "visit":p["visit"] if p else "", "homepage":m.get("homepage",""),
        "src_nise":m["in_nise"],"src_mohw":m["in_mohw"],"src_broso":"Y" if p else "",
    })
# broso에만 있는 기관 추가
have={norm(r["name"]) for r in rows}
added=0
for p in price:
    if norm(p["name"]) not in have and not any(norm(p["name"]) in h or h in norm(p["name"]) for h in have if len(h)>=6):
        rows.append({"name":p["name"],"sigungu":p["sigungu"],"address":"","tel":"","lat":"","lon":"",
                     "biz_no":p["biz_no"],"areas":p["areas"],"area_count":p["area_count"],
                     "price_min":p["price_min"],"price_max":p["price_max"],"visit":p["visit"],
                     "homepage":"","src_nise":"","src_mohw":"","src_broso":"Y"}); added+=1
rows.sort(key=lambda r:(r["sigungu"],r["name"]))
with io.open(D("data","seoul_final.csv"),"w",encoding="utf-8-sig",newline="") as fp:
    w=csv.DictWriter(fp,fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)

n=len(rows)
o=io.open(D("data","final_report.txt"),"w",encoding="utf-8"); w=lambda *a:o.write(" ".join(str(z) for z in a)+"\n")
w("서울 발달재활 기관 최종 DB : %d건  (broso 신규 %d건 추가)"%(n,added))
w("")
for lab,key in (("기관명·주소","name"),("전화번호","tel"),("위경도","lat"),
                ("치료영역","areas"),("회기당 단가","price_min"),
                ("사업자등록번호","biz_no"),("방문서비스 여부","visit"),("홈페이지","homepage")):
    c=sum(1 for r in rows if r[key])
    w("   %-16s %4d / %d   %5.1f%%"%(lab,c,n,100.0*c/n))
w("")
w("   출처 교차: NISE %d · 복지부 %d · broso %d"%(
    sum(1 for r in rows if r["src_nise"]),sum(1 for r in rows if r["src_mohw"]),sum(1 for r in rows if r["src_broso"])))
o.close(); print("ok")
