# -*- coding: utf-8 -*-
"""실제 벡터를 2차원으로 투영 -> 비전문가용 '의미 지도' 시각화 데이터
768차원 벡터를 PCA로 2축만 남겨 평면에 찍는다.
"""
import json, io, os, math
import numpy as np

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
D = lambda *p: os.path.join(BASE, *p)

docs = {d["id"]: d for d in (json.loads(l) for l in
        io.open(D("data", "kb", "kb_chunks.jsonl"), encoding="utf-8"))}
vec = {}
for l in io.open(D("data", "kb", "kb_vectors.jsonl"), encoding="utf-8"):
    r = json.loads(l)
    if r["id"] in docs:
        vec[r["id"]] = r["v"]
qv = json.load(io.open(D("data", "kb", "eval_query_vectors.json"), encoding="utf-8"))

# 주제가 뚜렷이 갈리는 네 묶음만 골라 평면이 읽히게 한다
GROUPS = [
    ("발달 기준", lambda d: d["type"] in ("developmental_milestone", "ksied_guide"), 130),
    ("질환 정보", lambda d: d["type"] in ("asd", "cp", "ds", "hearing", "vision",
                                          "intellectual", "tic", "condition"), 110),
    ("바우처 제도", lambda d: d["type"] in ("policy",), 20),
    ("치료영역 설명", lambda d: d["type"] in ("therapy_area", "therapy_mapping"), 25),
]

picked, labels = [], []
for name, fn, cap in GROUPS:
    n = 0
    for i, d in docs.items():
        if i in vec and fn(d):
            picked.append(i); labels.append(name); n += 1
            if n >= cap:
                break

Q = [
    ("24개월인데 아직 의미 있는 단어를 못 말해요. 괜찮은 건가요?", "발달 질문"),
    ("바우처 받으려면 소득이 얼마 이하여야 하나요?", "제도 질문"),
    ("감각발달재활이 뭐예요?", "용어 질문"),
]
Q = [(q, lab) for q, lab in Q if q in qv]

M = np.array([vec[i] for i in picked] + [qv[q] for q, _ in Q], dtype=float)
M /= np.linalg.norm(M, axis=1, keepdims=True)

# t-SNE: 국소 이웃(가까운 문장끼리 모임)을 보존하는 투영.
# PCA는 2축 설명력이 25%에 그쳐 주제 군집이 겹쳤다.
from sklearn.manifold import TSNE
P = TSNE(n_components=2, perplexity=24, init="pca", learning_rate="auto",
         metric="cosine", random_state=7, max_iter=1500).fit_transform(M)

mn, mx = P.min(axis=0), P.max(axis=0)
P = (P - mn) / (mx - mn) * 100

nd = len(picked)
points = [{"x": round(float(P[k, 0]), 2), "y": round(float(P[k, 1]), 2),
           "g": labels[k], "t": docs[picked[k]]["text"][:70]} for k in range(nd)]

# 질문별 가장 가까운 3개(원본 768차원 기준)
def cos(a, b):
    a = np.array(a); b = np.array(b)
    return float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b)))

queries = []
for j, (qtext, qlab) in enumerate(Q):
    k = nd + j
    sims = sorted(((cos(qv[qtext], vec[i]), i) for i in vec), reverse=True)[:3]
    near = []
    for s, i in sims:
        idx = picked.index(i) if i in picked else None
        near.append({"s": round(s, 3), "t": docs[i]["text"][:62],
                     "x": round(float(P[idx, 0]), 2) if idx is not None else None,
                     "y": round(float(P[idx, 1]), 2) if idx is not None else None})
    queries.append({"x": round(float(P[k, 0]), 2), "y": round(float(P[k, 1]), 2),
                    "label": qlab, "text": qtext, "near": near})

out = {"points": points, "queries": queries,
       "groups": [g[0] for g in GROUPS],
       "method": "t-SNE (cosine, perplexity 24)"}
io.open(D("data", "kb", "map2d.json"), "w", encoding="utf-8").write(
    json.dumps(out, ensure_ascii=False))
print("map2d.json 저장 - 점 %d개 / 질문 %d개" % (len(points), len(queries)))
print("투영: %s" % out["method"])
for q in queries:
    print("  [%s] 최근접 %.3f %s" % (q["label"], q["near"][0]["s"], q["near"][0]["t"][:40]))
