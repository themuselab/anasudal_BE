# -*- coding: utf-8 -*-
"""공공데이터포털 전수 스캔: 발달재활 관련 데이터셋 중 '치료영역/전문분야/서비스종류'를 가진 게 있는지 확인"""
import re, io, os, html, subprocess, urllib.parse, time

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120"
KEYWORDS = ["발달재활", "아동발달", "언어치료", "놀이치료", "장애아동", "사회서비스 제공기관", "심리상담"]
# 상세 데이터가 있다면 제목이나 설명에 반드시 등장할 단어들
SIGNAL = ["치료영역", "전문분야", "서비스종류", "제공서비스", "서비스분야", "프로그램",
          "단가", "이용료", "치료비", "운영시간", "정원", "대기", "종사자", "치료사", "제공인력"]

def fetch(kw, page):
    url = ("https://www.data.go.kr/tcs/dss/selectDataSetList.do?dType=&keyword=%s&currentPage=%d&perPage=10"
           % (urllib.parse.quote(kw), page))
    p = subprocess.run(["curl", "-s", "-m", "35", "-A", UA, url], capture_output=True)
    return p.stdout.decode("utf-8", "replace")

ITEM = re.compile(r'<a href="(/data/\d+/[a-zA-Z]+\.do)"[^>]*>(.*?)</a>.*?'
                  r'<span class="apply-result-summary">(.*?)</span>', re.S)

def clean(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", s))).strip()

seen, hits = {}, []
for kw in KEYWORDS:
    for page in range(1, 6):          # 키워드당 최대 50건
        h = fetch(kw, page)
        found = ITEM.findall(h)
        if not found:
            break
        for href, title, desc in found:
            t, d = clean(title), clean(desc)
            if href in seen:
                continue
            seen[href] = (t, d)
            sig = [s for s in SIGNAL if s in t or s in d]
            if sig:
                hits.append((href, t, d, sig))
        time.sleep(0.3)

o = io.open(os.path.join(BASE, "data", "datago_scan.txt"), "w", encoding="utf-8")
w = lambda *a: o.write(" ".join(str(z) for z in a) + "\n")
w("공공데이터포털 스캔 — 키워드 %d개, 고유 데이터셋 %d개 확인" % (len(KEYWORDS), len(seen)))
w("")
w("=== 상세 데이터 신호가 있는 데이터셋 (%d건) ===" % len(hits))
for href, t, d, sig in hits:
    w("  [%s] %s" % (", ".join(sig), t))
    w("      https://www.data.go.kr%s" % href)
    w("      %s" % d[:160])
w("")
w("=== 발달재활/아동발달 기관 관련 데이터셋 전체 ===")
for href, (t, d) in seen.items():
    if any(k in t for k in ("발달재활", "아동발달", "언어", "놀이", "장애아동", "제공기관")):
        w("  %-60s %s" % (t[:58], href))
o.close()
print("done")
