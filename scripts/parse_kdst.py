# -*- coding: utf-8 -*-
"""K-DST PDF -> 연령구간 × 영역 × 문항 구조화 (표 추출 기반)
출처: 질병관리청·보건복지부 한국 영유아 발달선별검사(K-DST) 개정판
"""
import pdfplumber, re, csv, io, os, glob, collections

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
D = lambda *p: os.path.join(BASE, *p)
DOMAINS = ["대근육운동", "소근육운동", "인지", "언어", "사회성", "자조"]

def month_of(fn):
    m = re.search(r"KDST_(\d+)-(\d+)m", fn)
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)

def clean(s):
    return re.sub(r"\s+", " ", (s or "")).strip()

rows = []
for p in sorted(glob.glob(D("data", "raw", "kdst", "KDST_*.pdf")), key=lambda x: month_of(os.path.basename(x))):
    lo, hi = month_of(os.path.basename(p))
    items = []            # (page, y, no, question)
    dom_marks = []        # (page, y, domain)
    with pdfplumber.open(p) as pdf:
        for pi, pg in enumerate(pdf.pages):
            # 영역 제목 위치
            for w in pg.extract_words():
                t = w["text"].strip()
                if t in DOMAINS:
                    dom_marks.append((pi, w["top"], t))
            # 문항 표 (번호 | 문항 | 척도)
            for tbl in pg.find_tables():
                data = tbl.extract()
                for ri, r in enumerate(data):
                    if len(r) < 2: continue
                    no, q = clean(r[0]), clean(r[1])
                    if not re.fullmatch(r"\d{1,2}", no): continue
                    if len(q) < 5: continue
                    y = tbl.bbox[1] + (tbl.bbox[3] - tbl.bbox[1]) * ri / max(len(data), 1)
                    items.append((pi, y, int(no), q))
    # 각 문항에 가장 가까운 앞선 영역 제목 할당
    dom_marks.sort()
    for pi, y, no, q in items:
        cur = ""
        for dpi, dy, dname in dom_marks:
            if (dpi, dy) <= (pi, y):
                cur = dname
            else:
                break
        if cur:
            rows.append({"age_lo": lo, "age_hi": hi, "age_label": "%d~%d개월" % (lo, hi),
                         "domain": cur, "no": no, "question": q})

out, seen = [], set()
for r in rows:
    k = (r["age_lo"], r["domain"], r["no"])
    if k in seen: continue
    seen.add(k); out.append(r)
out.sort(key=lambda r: (r["age_lo"], DOMAINS.index(r["domain"]), r["no"]))

with io.open(D("data", "kdst_items.csv"), "w", encoding="utf-8-sig", newline="") as fp:
    w = csv.DictWriter(fp, fieldnames=["age_lo", "age_hi", "age_label", "domain", "no", "question"])
    w.writeheader(); w.writerows(out)

print("총 %d문항 / %d개 연령구간" % (len(out), len({r["age_lo"] for r in out})))
for k, v in collections.Counter(r["domain"] for r in out).most_common():
    print("  %-8s %4d" % (k, v))
print()
byage = collections.Counter(r["age_label"] for r in out)
for k, v in sorted(byage.items(), key=lambda x: int(x[0].split("~")[0])):
    print("  %-12s %2d문항" % (k, v))
