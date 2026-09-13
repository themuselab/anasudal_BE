# -*- coding: utf-8 -*-
"""RAG 검색 평가 — Gemini 임베딩 (코사인 유사도)
BM25 베이스라인과 동일한 질문셋·판정 기준으로 비교
사용: GEMINI_KEY=<키> python scripts/eval_embedding.py
"""
import json, io, os, sys, math, subprocess, tempfile, time, collections

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
D = lambda *p: os.path.join(BASE, *p)
KEY = os.environ.get("GEMINI_KEY", "").strip()
MODEL = "models/gemini-embedding-2"
DIM = 768
QCACHE = D("data", "kb", "eval_query_vectors.json")


def embed_queries(texts):
    """질문 임베딩 (캐시). RETRIEVAL_QUERY 태스크 타입 사용"""
    cache = {}
    if os.path.exists(QCACHE):
        cache = json.load(io.open(QCACHE, encoding="utf-8"))
    todo = [t for t in texts if t not in cache]
    if todo and KEY:
        url = ("https://generativelanguage.googleapis.com/v1beta/%s:batchEmbedContents?key=%s" % (MODEL, KEY))
        for i in range(0, len(todo), 30):
            part = todo[i:i + 30]
            payload = {"requests": [{
                "model": MODEL,
                "content": {"parts": [{"text": t}]},
                "taskType": "RETRIEVAL_QUERY",
                "outputDimensionality": DIM,
            } for t in part]}
            fd, path = tempfile.mkstemp(suffix=".json")
            os.close(fd)
            io.open(path, "w", encoding="utf-8").write(json.dumps(payload, ensure_ascii=False))
            p = subprocess.run(["curl", "-s", "-m", "120", "-X", "POST", url,
                                "-H", "Content-Type: application/json",
                                "--data-binary", "@" + path], capture_output=True)
            os.remove(path)
            try:
                res = json.loads(p.stdout.decode("utf-8", "replace"))
            except Exception:
                res = {}
            embs = res.get("embeddings")
            if not embs:
                print("질문 임베딩 실패: %s" % json.dumps(res, ensure_ascii=False)[:160])
                break
            for t, e in zip(part, embs):
                cache[t] = e["values"]
            time.sleep(2)
        io.open(QCACHE, "w", encoding="utf-8").write(json.dumps(cache, ensure_ascii=False))
    return cache


def norm(v):
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def is_hit(doc, q):
    if q.get("expect_types") and doc["type"] in q["expect_types"]:
        return True
    for kw in q.get("expect_keywords", []):
        if kw in doc["text"]:
            return True
    return False


def age_ok(doc, age):
    m = doc.get("meta", {})
    lo, hi = m.get("age_lo"), m.get("age_hi")
    if lo is None or hi is None or age is None:
        return True
    return lo <= age <= hi or (age > 71 and hi >= 60)


def main():
    docs = {d["id"]: d for d in
            (json.loads(l) for l in io.open(D("data", "kb", "kb_chunks.jsonl"), encoding="utf-8"))}
    vecs = {}
    for l in io.open(D("data", "kb", "kb_vectors.jsonl"), encoding="utf-8"):
        r = json.loads(l)
        if r["id"] in docs:
            vecs[r["id"]] = norm(r["v"])
    ids = list(vecs.keys())
    qs = json.load(io.open(D("data", "kb", "eval_questions.json"), encoding="utf-8"))
    targets = [q for q in qs if q.get("tier", 1) in (1, 2)]

    qv = embed_queries([q["question"] for q in qs])
    have = [q for q in targets if q["question"] in qv]

    out = io.open(D("data", "kb", "eval_report_embedding.txt"), "w", encoding="utf-8")
    w = lambda *a: out.write(" ".join(str(z) for z in a) + "\n")
    w("RAG 검색 평가 — Gemini 임베딩 (gemini-embedding-2, %d차원)" % DIM)
    w("  벡터화된 청크 %d / 전체 %d (%.0f%%)" % (len(vecs), len(docs), 100.0 * len(vecs) / len(docs)))
    w("  평가 질문 %d개" % len(have))
    w("")
    if len(vecs) < len(docs):
        w("  ※ 일일 쿼터로 일부 청크가 미벡터화 상태 — 전량 완료 시 수치가 더 올라갈 수 있음")
        w("")

    def search(q, k, use_filter):
        v = qv[q["question"]]
        v = norm(v)
        age = q.get("age_months")
        sc = []
        for i in ids:
            d = docs[i]
            if use_filter and not age_ok(d, age):
                continue
            dv = vecs[i]
            sc.append((sum(a * b for a, b in zip(v, dv)), i))
        sc.sort(reverse=True)
        return [(s, docs[i]) for s, i in sc[:k]]

    w("=== ① top_k별 성능 ===")
    w("   %-6s %-24s %s" % ("top_k", "필터 없음", "연령 필터 적용"))
    for k in (1, 3, 5, 10, 20):
        line = []
        for uf in (False, True):
            rec = prec = 0.0
            for q in have:
                hits = search(q, k, uf)
                rel = [1 if is_hit(d, q) else 0 for _, d in hits]
                rec += 1.0 if any(rel) else 0.0
                prec += (sum(rel) / len(rel)) if rel else 0.0
            n = len(have)
            line.append((100.0 * rec / n, 100.0 * prec / n))
        w("   %-6d 적중 %3.0f%% 정밀 %3.0f%%       적중 %3.0f%% 정밀 %3.0f%%"
          % (k, line[0][0], line[0][1], line[1][0], line[1][1]))
    w("")

    w("=== ② 코사인 유사도 분포 (임계값 근거) ===")
    pos, neg = [], []
    for q in have:
        for s, d in search(q, 20, True):
            (pos if is_hit(d, q) else neg).append(s)
    pos.sort(); neg.sort()
    pctl = lambda a, p: a[int(len(a) * p)] if a else 0.0
    if pos and neg:
        w("   관련 문서  n=%-4d min %.3f / 10%% %.3f / 중앙 %.3f / 90%% %.3f / max %.3f"
          % (len(pos), pos[0], pctl(pos, .1), pctl(pos, .5), pctl(pos, .9), pos[-1]))
        w("   무관 문서  n=%-4d min %.3f / 10%% %.3f / 중앙 %.3f / 90%% %.3f / max %.3f"
          % (len(neg), neg[0], pctl(neg, .1), pctl(neg, .5), pctl(neg, .9), neg[-1]))
        best = None
        for t in [x / 100.0 for x in range(30, 95)]:
            tp = sum(1 for s in pos if s >= t)
            fp = sum(1 for s in neg if s >= t)
            fn = len(pos) - tp
            if tp == 0:
                continue
            p, r = tp / (tp + fp), tp / (tp + fn)
            f1 = 2 * p * r / (p + r)
            if best is None or f1 > best[3]:
                best = (t, p, r, f1)
        if best:
            w("")
            w("   F1 최적 임계값: %.2f  (정밀 %.0f%% / 재현 %.0f%% / F1 %.2f)"
              % (best[0], 100 * best[1], 100 * best[2], best[3]))
        w("   → 90%% 재현율 컷: %.3f" % pctl(pos, .1))
        w("   ※ 0.9 이상으로 잡으면 관련 문서의 %.0f%%가 버려짐"
          % (100.0 * sum(1 for s in pos if s < 0.9) / len(pos)))
    w("")

    w("=== ③ BM25에서 실패했던 질문 ===")
    for qid in ("Q19", "Q20", "Q21", "Q29"):
        q = next((x for x in have if x["id"] == qid), None)
        if not q:
            continue
        hits = search(q, 5, True)
        rel = [is_hit(d, q) for _, d in hits]
        w("")
        w(" [%s] %s  %s" % (q["id"], "O" if any(rel) else "X", q["question"][:50]))
        for (s, d), r in zip(hits, rel):
            w("      %s %.3f [%-18s] %s" % ("*" if r else " ", s, d["type"], d["text"][:58]))

    w("")
    w("=== ④ 폴백(tier 3) 질문 ===")
    for q in [x for x in qs if x.get("tier") == 3 and x["question"] in qv]:
        hits = search(q, 3, False)
        w("  [%s] %s → 최고 유사도 %.3f" % (q["id"], q["question"][:42], hits[0][0] if hits else 0))
        for s, d in hits[:2]:
            w("        %.3f [%s] %s" % (s, d["type"], d["text"][:52]))

    w("")
    w("=== ⑤ 전체 질문 결과 (필터+top5) ===")
    fails = []
    for q in have:
        hits = search(q, 5, True)
        ok = any(is_hit(d, q) for _, d in hits)
        if not ok:
            fails.append(q)
        w("  [%s] %s %s" % (q["id"], "O" if ok else "X", q["question"][:52]))
    w("")
    w("실패 %d개: %s" % (len(fails), ", ".join(q["id"] for q in fails)))
    out.close()
    print(io.open(D("data", "kb", "eval_report_embedding.txt"), encoding="utf-8").read()[:1200])


if __name__ == "__main__":
    main()
