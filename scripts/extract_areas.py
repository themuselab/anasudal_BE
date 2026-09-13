# -*- coding: utf-8 -*-
"""협약기관 홈페이지 -> 치료영역 추출 (규칙 기반 baseline; LLM 태깅의 입력 확보 가능성 검증)"""
import csv, io, os, re, subprocess, collections, time

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
rows = list(csv.DictReader(io.open(os.path.join(BASE,"data","seouli_clinics.csv"), encoding="utf-8-sig")))

AREAS = {
    "SPEECH":  ["언어치료","언어재활","조음","말더듬","언어발달"],
    "COGNI":   ["인지치료","인지학습","학습치료","인지발달"],
    "PLAY":    ["놀이치료","모래놀이"],
    "ART":     ["미술치료"],
    "MUSIC":   ["음악치료"],
    "SENSORY": ["감각통합"],
    "SOCIAL":  ["사회성"],
    "BEHAV":   ["행동치료","ABA","응용행동"],
    "PHYS":    ["심리운동","작업치료","물리치료","운동치료"],
}
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120"

def fetch(url):
    if "blog.naver.com" in url and "m.blog" not in url:
        url = url.replace("blog.naver.com", "m.blog.naver.com")
    p = subprocess.run(["curl","-sL","-m","25","-k","-A",UA,url], capture_output=True)
    b = p.stdout
    for enc in ("utf-8","euc-kr","cp949"):
        try: return b.decode(enc)
        except Exception: pass
    return b.decode("utf-8","replace")

def text_of(h):
    h = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", h, flags=re.S|re.I)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", h))

N = int(os.environ.get("N", "12"))
targets = rows[:N]
res, stat = [], collections.Counter()
for r in targets:
    if not r["homepage"]:
        stat["NO_URL"] += 1; continue
    t = text_of(fetch(r["homepage"]))
    found = sorted({code for code, kws in AREAS.items() if any(k in t for k in kws)})
    stat["OK" if found else "FETCH_NO_AREA"] += 1
    res.append((r["name"], r["hp_type"], len(t), found))
    time.sleep(0.5)

o = io.open(os.path.join(BASE,"data","area_extraction_report.txt"), "w", encoding="utf-8")
w = lambda *a: o.write(" ".join(str(x) for x in a) + "\n")
w("대상: 서울아이발달지원센터 협약기관 홈페이지 %d곳" % len(targets))
w("결과: 치료영역 추출 성공 %d / 본문은 받았으나 영역 없음 %d / URL 없음 %d"
  % (stat["OK"], stat["FETCH_NO_AREA"], stat["NO_URL"]))
w("")
for n, ht, ln, f in res:
    w("  %-34s %-10s %6d자  %s" % (n[:32], ht, ln, ", ".join(f) if f else "-"))
o.close()
print(open(os.path.join(BASE,"data","area_extraction_report.txt"), encoding="utf-8").read())
