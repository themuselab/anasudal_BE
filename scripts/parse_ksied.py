# -*- coding: utf-8 -*-
"""새싹과단비(삼성복지재단 x 육아정책연구소) 발달길잡이 파싱
  loadGuide.do      -> 연령별 영역별 발달특징 (K-DST 교차검증용 제2축)
  loadCheckList.do  -> 연령별 경고신호 체크리스트
"""
import re, csv, io, os, json, glob, collections

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
D = lambda *p: os.path.join(BASE, *p)
SRC = "새싹과단비 (삼성복지재단·육아정책연구소) 발달길잡이"

IDX_AGE = {
    "1": ("2개월", 2, 2), "4": ("4개월", 4, 4), "5": ("6개월", 6, 6), "6": ("9개월", 9, 9),
    "7": ("12~17개월", 12, 17), "8": ("18~23개월", 18, 23), "9": ("24~29개월", 24, 29),
    "10": ("30~35개월", 30, 35), "11": ("3세", 36, 47), "12": ("4세", 48, 59), "13": ("5세", 60, 71),
}
DOMAINS = ["인지", "언어", "운동", "사회정서", "자조"]


def strip_tags(html):
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    return html


def items_of(html):
    """<li> 또는 <p> 단위 텍스트 추출"""
    out = []
    for m in re.finditer(r"<(li|p|td)[^>]*>(.*?)</\1>", html, re.S | re.I):
        t = re.sub(r"<[^>]+>", " ", m.group(2))
        t = re.sub(r"&nbsp;|&amp;", " ", t)
        t = re.sub(r"\s+", " ", t).strip()
        if 6 <= len(t) <= 300:
            out.append(t)
    return out


guide_rows, check_rows = [], []

for p in sorted(glob.glob(D("data", "raw", "ksied", "loadGuide_*.html"))):
    idx = re.search(r"loadGuide_(\d+)", p).group(1)
    if idx not in IDX_AGE:
        continue
    label, lo, hi = IDX_AGE[idx]
    html = strip_tags(open(p, "rb").read().decode("utf-8", "replace"))
    # 영역 구분자로 분할
    marks = []
    for m in re.finditer(r"(%s)\s*영역" % "|".join(DOMAINS), html):
        marks.append((m.start(), m.group(1)))
    marks.sort()
    # 영역 이전 구간은 '발달이정표'(총평)
    head = html[: marks[0][0]] if marks else html
    for t in items_of(head):
        if re.search(r"참고자료|출처|발달이정표|발달특징|각 영역별", t):
            continue
        guide_rows.append({"age_label": label, "age_lo": lo, "age_hi": hi,
                           "domain": "종합", "item": t})
    for i, (pos, dom) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(html)
        for t in items_of(html[pos:end]):
            if re.search(r"영역$|참고자료|출처|아래의 행동", t) or t.startswith(dom):
                continue
            guide_rows.append({"age_label": label, "age_lo": lo, "age_hi": hi,
                               "domain": dom, "item": t})

for p in sorted(glob.glob(D("data", "raw", "ksied", "loadCheckList_*.html"))):
    idx = re.search(r"loadCheckList_(\d+)", p).group(1)
    if idx not in IDX_AGE:
        continue
    label, lo, hi = IDX_AGE[idx]
    html = strip_tags(open(p, "rb").read().decode("utf-8", "replace"))
    for t in items_of(html):
        if re.search(r"체크|해당|없음|선택", t) and len(t) < 15:
            continue
        check_rows.append({"age_label": label, "age_lo": lo, "age_hi": hi, "warning": t})

# 중복 제거
def dedup(rows, key):
    seen, out = set(), []
    for r in rows:
        k = tuple(r[c] for c in key)
        if k in seen:
            continue
        seen.add(k)
        out.append(r)
    return out

guide_rows = dedup(guide_rows, ("age_label", "domain", "item"))
check_rows = dedup(check_rows, ("age_label", "warning"))

with io.open(D("data", "kb", "kb_ksied_guide.csv"), "w", encoding="utf-8-sig", newline="") as fp:
    w = csv.DictWriter(fp, fieldnames=["age_label", "age_lo", "age_hi", "domain", "item"])
    w.writeheader(); w.writerows(guide_rows)
with io.open(D("data", "kb", "kb_ksied_warning.csv"), "w", encoding="utf-8-sig", newline="") as fp:
    w = csv.DictWriter(fp, fieldnames=["age_label", "age_lo", "age_hi", "warning"])
    w.writeheader(); w.writerows(check_rows)

# 청크 반영
chunks = []
for ln in io.open(D("data", "kb", "kb_chunks.jsonl"), encoding="utf-8"):
    c = json.loads(ln)
    if c["type"] not in ("ksied_guide", "ksied_warning"):
        chunks.append(c)
for i, r in enumerate(guide_rows):
    chunks.append({"id": "ksied_g_%d" % i, "type": "ksied_guide",
                   "text": "%s 아동의 %s 발달특징: %s" % (r["age_label"], r["domain"], r["item"]),
                   "meta": {"age_lo": r["age_lo"], "age_hi": r["age_hi"], "domain": r["domain"]},
                   "source": SRC})
for i, r in enumerate(check_rows):
    chunks.append({"id": "ksied_w_%d" % i, "type": "ksied_warning",
                   "text": "%s 아동의 발달 경고신호: %s" % (r["age_label"], r["warning"]),
                   "meta": {"age_lo": r["age_lo"], "age_hi": r["age_hi"], "severity": "warning"},
                   "source": SRC})
with io.open(D("data", "kb", "kb_chunks.jsonl"), "w", encoding="utf-8") as fp:
    for c in chunks:
        fp.write(json.dumps(c, ensure_ascii=False) + "\n")

print("새싹과단비 파싱 완료")
print("  발달특징 %d건 / 경고신호 %d건" % (len(guide_rows), len(check_rows)))
print()
print("=== 연령구간별 발달특징 ===")
for k, v in sorted(collections.Counter(r["age_label"] for r in guide_rows).items(),
                   key=lambda x: [r for r in guide_rows if r["age_label"] == x[0]][0]["age_lo"]):
    w = sum(1 for r in check_rows if r["age_label"] == k)
    print("  %-12s 발달특징 %2d · 경고신호 %2d" % (k, v, w))
print()
print("=== 영역별 ===")
for k, v in collections.Counter(r["domain"] for r in guide_rows).most_common():
    print("  %-8s %3d" % (k, v))
print()
print("총 청크 %d" % len(chunks))
