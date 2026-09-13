# -*- coding: utf-8 -*-
"""서울아이발달지원센터 협약 치료기관(86) 파싱 + NISE 382와 매칭.
이 목록의 가치: 기관별 '홈페이지 URL'을 제공하는 유일한 공적 소스.
"""
import re, csv, io, os

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
h = open(os.path.join(BASE, "data", "raw", "seouli_clinic.html"), "rb").read().decode("utf-8", "replace")

LI = re.compile(
    r'<li>\s*<dl>\s*<dt>(?P<name>.*?)</dt>\s*'
    r'<dd class="numeric">(?P<tel>.*?)</dd>\s*'
    r'<dd>(?P<addr>.*?)</dd>\s*</dl>\s*'
    r'<div class="link">(?P<link>.*?)</div>\s*</li>', re.S)

def clean(s):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", s or "")).strip()

def gu(a):
    m = re.search(r"([가-힣]{1,4}구)(?:\s|$)", a)
    return m.group(1) if m else ""

rows = []
for m in LI.finditer(h):
    mu = re.search(r'<a href="([^"]+)"', m.group("link"))
    url = mu.group(1) if mu else ""
    addr = clean(m.group("addr"))
    rows.append({
        "name": clean(m.group("name")),
        "tel": clean(m.group("tel")),
        "sigungu": gu(addr),
        "address": addr,
        "homepage": url,
        "hp_type": ("naver_blog" if "blog.naver" in url else
                    "none" if not url else "own_site"),
    })

out = os.path.join(BASE, "data", "seouli_clinics.csv")
with io.open(out, "w", encoding="utf-8-sig", newline="") as fp:
    w = csv.DictWriter(fp, fieldnames=list(rows[0].keys()))
    w.writeheader(); w.writerows(rows)

# NISE 382와 매칭 (전화번호 정규화 우선, 실패 시 기관명)
nise = list(csv.DictReader(io.open(os.path.join(BASE,"data","seoul_agencies_nise.csv"), encoding="utf-8-sig")))
def digits(t): return re.sub(r"\D", "", t or "")
nise_tel  = {digits(r["tel"]): r for r in nise if digits(r["tel"])}
nise_name = {re.sub(r"[\s()㈜]", "", r["name"]): r for r in nise}

by_tel = by_name = 0
for r in rows:
    if digits(r["tel"]) in nise_tel: by_tel += 1
    elif re.sub(r"[\s()㈜]", "", r["name"]) in nise_name: by_name += 1

import collections
c = collections.Counter(r["hp_type"] for r in rows)
print("협약기관 파싱: %d건 -> %s" % (len(rows), out))
print("홈페이지 유형: %s" % dict(c))
print("NISE 382와 매칭: 전화일치 %d + 기관명일치 %d = %d건 (%.0f%%)"
      % (by_tel, by_name, by_tel+by_name, 100.0*(by_tel+by_name)/len(rows)))
