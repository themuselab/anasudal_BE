# -*- coding: utf-8 -*-
"""발표용 차트 데이터 추출 -> data/kb/chart_data.json"""
import json, io, os, math, csv, collections, re, sys

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
D = lambda *p: os.path.join(BASE, *p)
sys.path.insert(0, D("scripts"))

from eval_retrieval import BM25, age_filter, is_hit  # noqa

docs = [json.loads(l) for l in io.open(D("data", "kb", "kb_chunks.jsonl"), encoding="utf-8")]
qs = json.load(io.open(D("data", "kb", "eval_questions.json"), encoding="utf-8"))
targets = [q for q in qs if q.get("tier", 1) in (1, 2)]

# ── 임베딩 검색
byid = {d["id"]: d for d in docs}
vec = {}
for l in io.open(D("data", "kb", "kb_vectors.jsonl"), encoding="utf-8"):
    r = json.loads(l)
    if r["id"] in byid:
        n = math.sqrt(sum(x * x for x in r["v"])) or 1.0
        vec[r["id"]] = [x / n for x in r["v"]]
qv = json.load(io.open(D("data", "kb", "eval_query_vectors.json"), encoding="utf-8"))


def age_ok(d, age):
    m = d.get("meta", {})
    lo, hi = m.get("age_lo"), m.get("age_hi")
    if lo is None or hi is None or age is None:
        return True
    return lo <= age <= hi or (age > 71 and hi >= 60)


def emb_search(q, k, use_filter=True):
    v = qv[q["question"]]
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    v = [x / n for x in v]
    age = q.get("age_months")
    sc = []
    for i, dv in vec.items():
        d = byid[i]
        if use_filter and not age_ok(d, age):
            continue
        sc.append((sum(a * b for a, b in zip(v, dv)), i))
    sc.sort(reverse=True)
    return [(s, byid[i]) for s, i in sc[:k]]


bm = BM25(docs)
out = {}

# ① top_k 성능
ks = [1, 3, 5, 10, 20]
perf = {"k": ks, "bm25_recall": [], "bm25_prec": [], "emb_recall": [], "emb_prec": [],
        "emb_recall_nofilter": []}
for k in ks:
    for tag, fn in (("bm25", None), ("emb", True), ("embnf", False)):
        rec = prec = 0.0
        for q in targets:
            if tag == "bm25":
                cand = age_filter(docs, q.get("age_months"))
                hits = bm.search(q["question"], cand, top_k=k)
            else:
                hits = emb_search(q, k, use_filter=(tag == "emb"))
            rel = [1 if is_hit(d, q) else 0 for _, d in hits]
            rec += 1.0 if any(rel) else 0.0
            prec += (sum(rel) / len(rel)) if rel else 0.0
        n = len(targets)
        if tag == "bm25":
            perf["bm25_recall"].append(round(100 * rec / n, 1))
            perf["bm25_prec"].append(round(100 * prec / n, 1))
        elif tag == "emb":
            perf["emb_recall"].append(round(100 * rec / n, 1))
            perf["emb_prec"].append(round(100 * prec / n, 1))
        else:
            perf["emb_recall_nofilter"].append(round(100 * rec / n, 1))
out["topk"] = perf

# ② 유사도 분포 (원시 점수 -> 히스토그램)
pos, neg = [], []
for q in targets:
    for s, d in emb_search(q, 30, True):
        (pos if is_hit(d, q) else neg).append(s)
lo, hi, nb = 0.45, 0.95, 25
step = (hi - lo) / nb
bins = [round(lo + i * step, 4) for i in range(nb)]


def hist(a):
    h = [0] * nb
    for s in a:
        j = min(nb - 1, max(0, int((s - lo) / step)))
        h[j] += 1
    return h


out["similarity"] = {
    "bins": bins, "step": round(step, 4),
    "related": hist(pos), "unrelated": hist(neg),
    "n_related": len(pos), "n_unrelated": len(neg),
    "max_related": round(max(pos), 3), "max_unrelated": round(max(neg), 3),
    "median_related": round(sorted(pos)[len(pos) // 2], 3),
    "median_unrelated": round(sorted(neg)[len(neg) // 2], 3),
}

# ③ 기관 DB 필드 충족률
rows = list(csv.DictReader(io.open(D("data", "nationwide_master.csv"), encoding="utf-8-sig")))
N = len(rows)
fields = [("치료영역", "areas"), ("회기당 단가", "price_min"), ("사업자등록번호", "biz_no"),
          ("도로명주소", "address"), ("전화번호", "tel"), ("좌표", "lat"),
          ("이메일", "email"), ("자체 홈페이지", "own_homepage"),
          ("운영시간", "operating_hours"), ("대기 여부", "waiting")]
out["coverage"] = {
    "total": N,
    "labels": [f[0] for f in fields],
    "values": [round(100.0 * sum(1 for r in rows if r.get(f[1])) / N, 1) for f in fields],
}

# ④ KB 출처 구성
srcs = collections.Counter()
for d in docs:
    s = d["source"]
    if "K-DST" in s:
        k = "K-DST (질병관리청)"
    elif "새싹과단비" in s:
        k = "새싹과단비 (육아정책연구소)"
    elif "국가건강정보포털" in s:
        k = "국가건강정보포털 (질병관리청)"
    elif "전자바우처" in s:
        k = "사회서비스 전자바우처 (복지부)"
    else:
        k = "자체 매핑 (검증 대기)"
    srcs[k] += 1
items = srcs.most_common()
out["kb_source"] = {"labels": [k for k, _ in items], "values": [v for _, v in items],
                    "total": len(docs)}

# ⑤ 전국 치료영역 분포
areas = collections.Counter()
for r in rows:
    for a in (r["areas"] or "").split(" / "):
        if a and a != "기타":
            areas[a] += 1
items = areas.most_common()
out["therapy_area"] = {
    "labels": [k for k, _ in items],
    "values": [round(100.0 * v / N, 1) for _, v in items],
    "counts": [v for _, v in items], "total": N,
}

io.open(D("data", "kb", "chart_data.json"), "w", encoding="utf-8").write(
    json.dumps(out, ensure_ascii=False, indent=1))
print("chart_data.json 저장")
print(" topk      :", out["topk"]["emb_recall"])
print(" similarity: 관련 %d / 무관 %d (최대 %.3f vs %.3f)"
      % (out["similarity"]["n_related"], out["similarity"]["n_unrelated"],
         out["similarity"]["max_related"], out["similarity"]["max_unrelated"]))
print(" coverage  : %d곳" % out["coverage"]["total"])
print(" kb_source :", out["kb_source"]["values"])
