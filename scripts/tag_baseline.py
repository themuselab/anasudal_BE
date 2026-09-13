# -*- coding: utf-8 -*-
"""기관명만으로 치료영역 태깅이 얼마나 가능한지 측정하는 baseline.
문서 A-2 가정("기관명·소개문 LLM 태깅")의 상한선을 확인하기 위한 실험.
"""
import csv, io, re, collections, os

BASE = os.path.join(os.path.dirname(__file__), "..")
CSV_IN = os.path.join(BASE, "data", "seoul_agencies_nise.csv")
OUT = os.path.join(BASE, "data", "tag_baseline_report.txt")

# D-1 치료영역 코드 체계 (문서 기준)
KEYWORDS = {
    "SPEECH":  ["언어", "말", "구어", "스피치"],
    "COGNI":   ["인지", "학습", "심리인지"],
    "PLAY":    ["놀이"],
    "ART":     ["미술"],
    "MUSIC":   ["음악", "뮤직"],
    "SENSORY": ["감각", "감각통합"],
    "SOCIAL":  ["사회성", "또래"],
    "BEHAV":   ["행동", "ABA", "응용행동"],
    "PHYS":    ["운동", "물리", "작업치료", "재활운동"],
}

rows = list(csv.DictReader(io.open(CSV_IN, encoding="utf-8-sig")))
hit = collections.Counter()
tagged, untagged = 0, []

for r in rows:
    name = r["name"]
    tags = [code for code, kws in KEYWORDS.items() if any(k in name for k in kws)]
    if tags:
        tagged += 1
        for t in tags:
            hit[t] += 1
    else:
        untagged.append(name)

o = io.open(OUT, "w", encoding="utf-8")
w = lambda *a: o.write(" ".join(str(x) for x in a) + "\n")
w("대상 기관 수: %d" % len(rows))
w("기관명에서 치료영역 1개 이상 추출: %d건 (%.1f%%)" % (tagged, 100.0*tagged/len(rows)))
w("추출 실패: %d건 (%.1f%%)" % (len(untagged), 100.0*len(untagged)/len(rows)))
w("")
w("=== 영역별 히트 수 ===")
for k, v in hit.most_common():
    w("  %-8s %d" % (k, v))
w("")
w("=== 태깅 실패 기관명 샘플 30 ===")
for n in untagged[:30]:
    w("  " + n)
o.close()
print(open(OUT, encoding="utf-8").read()[:200])
