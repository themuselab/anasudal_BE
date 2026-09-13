# -*- coding: utf-8 -*-
"""NISE 온맘(장애자녀 부모지원 종합시스템) 발달재활서비스기관 목록 HTML -> CSV
출처: https://www.nise.go.kr/onmam/front/M0000101/agency/list.do
"""
import re, csv, glob, io, os, sys

RAW = os.path.join(os.path.dirname(__file__), "..", "data", "raw")
OUT = os.path.join(os.path.dirname(__file__), "..", "data", "seoul_agencies_nise.csv")

ROW = re.compile(
    r'<tr>\s*<td class="num">\s*(?P<no>\d+)</td>\s*'
    r'<td class="company">\s*<button[^>]*viewMorePop\',\s*\'(?P<sn>\d+)\'\)">\s*(?P<name>.*?)</button>\s*</td>\s*'
    r'<td class="address">(?P<addr>.*?)</td>\s*'
    r'<td class="call">(?P<tel>.*?)</td>', re.S)

def clean(s):
    s = re.sub(r'<!--.*?-->', '', s, flags=re.S)
    s = re.sub(r'<[^>]+>', '', s)
    return re.sub(r'\s+', ' ', s).strip()

def sigungu(addr):
    m = re.search(r'서울(?:특별시|시)?\s*([가-힣]{1,4}구)(?:\s|$)', addr)
    if m:
        return m.group(1)
    m = re.search(r'([가-힣]{1,4}구)\s', addr)
    return m.group(1) if m else ''

rows, seen = [], set()
for f in sorted(glob.glob(os.path.join(RAW, "nise_seoul_p*.html")),
                key=lambda p: int(re.search(r'p(\d+)\.html', p).group(1))):
    html = open(f, 'rb').read().decode('utf-8', 'replace')
    for m in ROW.finditer(html):
        sn = m.group('sn')
        if sn in seen:
            continue
        seen.add(sn)
        addr = clean(m.group('addr'))
        rows.append({
            "inst_sn": sn,
            "seq_no": m.group('no'),
            "name": clean(m.group('name')),
            "sido": "서울특별시",
            "sigungu": sigungu(addr),
            "address": addr,
            "tel": clean(m.group('tel')),
            "source": "NISE_onmam",
        })

with io.open(OUT, 'w', encoding='utf-8-sig', newline='') as fp:
    w = csv.DictWriter(fp, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)

print("총 %d건 -> %s" % (len(rows), os.path.abspath(OUT)))
missing_tel = sum(1 for r in rows if not r["tel"])
missing_gu = sum(1 for r in rows if not r["sigungu"])
print("전화번호 결측: %d / 자치구 파싱실패: %d" % (missing_tel, missing_gu))
