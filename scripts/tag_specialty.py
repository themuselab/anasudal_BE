# -*- coding: utf-8 -*-
"""기관 홈페이지 -> 특화분야 태깅.
어제 실패 원인 개선:
  1) 루트만 긁지 않고 프로그램/치료/소개 링크를 따라 들어감
  2) 네이버 블로그는 m.blog + PostList 경유
  3) 여러 페이지 본문을 합쳐서 태깅
"""
import csv, io, os, re, subprocess, collections, time
from urllib.parse import urljoin, urlparse

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
D = lambda *p: os.path.join(BASE, *p)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120"

# 잇다 23종 + broso 법정영역을 합친 택소노미
TAXONOMY = {
    "언어치료":   ["언어치료", "언어재활", "조음", "말더듬", "언어발달", "구어"],
    "인지치료":   ["인지치료", "인지학습", "학습치료", "인지발달"],
    "놀이치료":   ["놀이치료", "놀이심리"],
    "미술치료":   ["미술치료", "미술심리"],
    "음악치료":   ["음악치료", "음악재활"],
    "감각통합":   ["감각통합", "감각발달"],
    "심리치료":   ["심리치료", "심리상담", "정서치료"],
    "행동치료":   ["행동치료", "행동발달", "ABA", "응용행동", "긍정적행동지원"],
    "작업치료":   ["작업치료"],
    "물리치료":   ["물리치료"],
    "운동치료":   ["운동치료", "운동발달", "재활운동"],
    "심리운동":   ["심리운동"],
    "사회성":     ["사회성", "또래", "사회기술"],
    "그룹치료":   ["그룹치료", "집단치료", "그룹수업", "소그룹"],
    "짝치료":     ["짝치료", "페어수업"],
    "모래놀이":   ["모래놀이", "샌드플레이"],
    "특수체육":   ["특수체육", "적응체육"],
    "청능재활":   ["청능재활", "청각재활", "청능훈련"],
    "조기교실":   ["조기교실", "조기개입", "영유아교실"],
    "부모교육":   ["부모교육", "부모상담", "부모코칭", "양육코칭"],
    "발달검사":   ["발달검사", "심리평가", "발달평가", "진단평가"],
}
FOLLOW = re.compile(r"프로그램|치료|소개|서비스|program|service|intro|about|sub", re.I)

def fetch(url, timeout=20):
    p = subprocess.run(["curl", "-sL", "-m", str(timeout), "-k", "-A", UA, url], capture_output=True)
    b = p.stdout
    for enc in ("utf-8", "euc-kr", "cp949"):
        try: return b.decode(enc)
        except Exception: pass
    return b.decode("utf-8", "replace")

def text_of(h):
    h = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", h, flags=re.S | re.I)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", h))

def naver_variants(url):
    m = re.search(r"blog\.naver\.com/([A-Za-z0-9_\-]+)", url)
    if not m: return []
    bid = m.group(1)
    return [f"https://m.blog.naver.com/{bid}",
            f"https://blog.naver.com/PostList.naver?blogId={bid}&categoryNo=0",
            f"https://rss.blog.naver.com/{bid}.xml"]

def collect_text(url, max_pages=4):
    pages, seen = [], set()
    urls = ([url] + naver_variants(url)) if "blog.naver" in url else [url]
    for u in urls[:3]:
        if u in seen: continue
        seen.add(u)
        h = fetch(u)
        pages.append(text_of(h))
        if "blog.naver" not in u:
            # 내부 프로그램/치료 페이지 따라가기
            links = re.findall(r'href=["\']([^"\'#]{2,120})["\']', h)
            cand = [urljoin(u, l) for l in links if FOLLOW.search(l)]
            cand = [c for c in cand if urlparse(c).netloc == urlparse(u).netloc]
            for c in list(dict.fromkeys(cand))[:max_pages]:
                if c in seen: continue
                seen.add(c)
                pages.append(text_of(fetch(c, 15)))
    return " ".join(pages), len(seen)

def tag(txt):
    return sorted({code for code, kws in TAXONOMY.items() if any(k in txt for k in kws)})

rows = list(csv.DictReader(io.open(D("data", "seouli_clinics.csv"), encoding="utf-8-sig")))
out, stat = [], collections.Counter()
for i, r in enumerate(rows, 1):
    if not r["homepage"]:
        stat["NO_URL"] += 1; continue
    txt, npages = collect_text(r["homepage"])
    tags = tag(txt)
    stat["TAGGED" if tags else "FAIL"] += 1
    out.append({"name": r["name"], "sigungu": r["sigungu"], "tel": r["tel"],
                "homepage": r["homepage"], "hp_type": r["hp_type"],
                "pages": npages, "chars": len(txt),
                "specialty": ", ".join(tags), "n_specialty": len(tags)})
    if i % 20 == 0: print("  %d/%d tagged=%d" % (i, len(rows), stat["TAGGED"]), flush=True)
    time.sleep(0.3)

with io.open(D("data", "specialty_tagged.csv"), "w", encoding="utf-8-sig", newline="") as fp:
    w = csv.DictWriter(fp, fieldnames=list(out[0].keys())); w.writeheader(); w.writerows(out)

o = io.open(D("data", "specialty_report.txt"), "w", encoding="utf-8"); w = lambda *a: o.write(" ".join(str(z) for z in a) + "\n")
n = len(out)
w("특화분야 태깅 결과 : 대상 %d곳" % n)
w("  태깅 성공 : %d (%.0f%%)" % (stat["TAGGED"], 100.0 * stat["TAGGED"] / n))
w("  태깅 실패 : %d (%.0f%%)" % (stat["FAIL"], 100.0 * stat["FAIL"] / n))
w("")
w("=== 본문 확보량별 성공률 ===")
for lo, hi, lab in ((0, 500, "~500자"), (500, 3000, "500~3천"), (3000, 20000, "3천~2만"), (20000, 10**9, "2만자~")):
    g = [r for r in out if lo <= r["chars"] < hi]
    if g: w("   %-10s %3d곳 중 %3d곳 성공 (%.0f%%)" % (lab, len(g), sum(1 for r in g if r["specialty"]), 100.0 * sum(1 for r in g if r["specialty"]) / len(g)))
w("")
w("=== 특화분야 분포 ===")
c = collections.Counter(s for r in out for s in r["specialty"].split(", ") if s)
for k, v in c.most_common(): w("   %-10s %d" % (k, v))
w("")
w("=== 샘플 12 ===")
for r in sorted(out, key=lambda x: -x["n_specialty"])[:12]:
    w("   %-26s %s" % (r["name"][:24], r["specialty"]))
o.close()
print("DONE")
