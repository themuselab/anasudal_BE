# -*- coding: utf-8 -*-
"""RAG 검색 평가 하네스 (BM25 렉시컬 베이스라인)

측정 목적
  1) top_k를 몇으로 잡을 것인가
  2) 연령 메타 필터가 정확도를 얼마나 올리는가
  3) 유사도(점수) 임계값을 어디서 자를 것인가 -> 정답/오답 점수 분포로 결정

※ 임베딩이 아니라 어휘 기반 BM25이므로 절대 수치는 임베딩과 다릅니다.
   하지만 (a) 하네스 구조 (b) 연령 필터 효과 (c) 임계값을 '측정해서 정한다'는 절차는
   그대로 임베딩에 적용됩니다. 임베딩 모델을 붙이면 score 함수만 교체하면 됩니다.
"""
import json, io, os, re, math, collections, sys

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
D = lambda *p: os.path.join(BASE, *p)


# ───────────────────────── 토크나이저 ─────────────────────────
def tokenize(text):
    """한국어 어미 변화를 흡수하기 위해 어절 + 2~3그램 혼합"""
    text = re.sub(r"[^\w가-힣]+", " ", text)
    words = [w for w in text.split() if len(w) >= 2]
    toks = list(words)
    for w in words:
        if len(w) >= 3:
            toks.append(w[:2])          # 어간 근사
            toks.append(w[:3])
    for w in words:
        for n in (2, 3):
            for i in range(len(w) - n + 1):
                toks.append(w[i:i + n])
    return toks


# ───────────────────────── BM25 ─────────────────────────
class BM25:
    def __init__(self, docs, k1=1.5, b=0.75):
        self.k1, self.b = k1, b
        self.docs = docs
        self.toks = [tokenize(d["text"]) for d in docs]
        self.len = [len(t) for t in self.toks]
        self.avg = sum(self.len) / max(len(self.len), 1)
        self.tf = [collections.Counter(t) for t in self.toks]
        df = collections.Counter()
        for t in self.toks:
            for w in set(t):
                df[w] += 1
        N = len(docs)
        self.idf = {w: math.log(1 + (N - n + 0.5) / (n + 0.5)) for w, n in df.items()}

    def score(self, qtoks, i):
        s = 0.0
        tf, dl = self.tf[i], self.len[i]
        for w in qtoks:
            f = tf.get(w)
            if not f:
                continue
            s += self.idf.get(w, 0) * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * dl / self.avg))
        return s

    def search(self, query, cand=None, top_k=5):
        q = tokenize(query)
        idxs = cand if cand is not None else range(len(self.docs))
        scored = [(self.score(q, i), i) for i in idxs]
        scored.sort(reverse=True)
        return [(s, self.docs[i]) for s, i in scored[:top_k] if s > 0]


# ───────────────────────── 정답 판정 ─────────────────────────
def is_hit(doc, q):
    """expect_types 또는 expect_keywords를 만족하면 관련 문서로 간주"""
    if q.get("expect_types") and doc["type"] in q["expect_types"]:
        return True
    for kw in q.get("expect_keywords", []):
        if kw in doc["text"]:
            return True
    return False


def age_filter(docs, age_months):
    """연령 메타가 있는 문서는 해당 월령 구간만, 메타가 없는 문서는 항상 후보"""
    out = []
    for i, d in enumerate(docs):
        m = d.get("meta", {})
        lo, hi = m.get("age_lo"), m.get("age_hi")
        if lo is None or hi is None or age_months is None:
            out.append(i)
        elif lo <= age_months <= hi or (age_months > 71 and hi >= 60):
            out.append(i)
    return out


def main():
    docs = [json.loads(l) for l in io.open(D("data", "kb", "kb_chunks.jsonl"), encoding="utf-8")]
    qs = json.load(io.open(D("data", "kb", "eval_questions.json"), encoding="utf-8"))
    bm = BM25(docs)

    # tier 1~2만 검색 평가 대상 (tier 0=DB쿼리, tier 3=폴백 기대)
    targets = [q for q in qs if q.get("tier", 1) in (1, 2)]

    out = io.open(D("data", "kb", "eval_report.txt"), "w", encoding="utf-8")
    w = lambda *a: out.write(" ".join(str(z) for z in a) + "\n")

    w("RAG 검색 평가 — BM25 렉시컬 베이스라인")
    w("  문서 %d청크 / 질문 %d개 (검색평가 대상 %d개)" % (len(docs), len(qs), len(targets)))
    w("")

    # ── 1) top_k별 정확도 (연령 필터 유무 비교)
    w("=== ① top_k별 성능 ===")
    w("   %-6s %-22s %-22s" % ("top_k", "필터 없음", "연령 필터 적용"))
    rows = []
    for k in (1, 3, 5, 10, 20):
        res = {}
        for use_filter in (False, True):
            hit_at_1 = 0
            recall_sum = 0.0
            prec_sum = 0.0
            for q in targets:
                cand = age_filter(docs, q.get("age_months")) if use_filter else None
                hits = bm.search(q["question"], cand, top_k=k)
                rel = [1 if is_hit(d, q) else 0 for _, d in hits]
                if rel and rel[0]:
                    hit_at_1 += 1
                recall_sum += 1.0 if any(rel) else 0.0
                prec_sum += (sum(rel) / len(rel)) if rel else 0.0
            n = len(targets)
            res[use_filter] = (100.0 * hit_at_1 / n, 100.0 * recall_sum / n, 100.0 * prec_sum / n)
        rows.append((k, res[False], res[True]))
        w("   %-6d 적중 %3.0f%% 정밀 %3.0f%%     적중 %3.0f%% 정밀 %3.0f%%"
          % (k, res[False][1], res[False][2], res[True][1], res[True][2]))
    w("")
    w("   적중률 = 상위 k개 안에 관련 문서가 1개라도 있는 질문 비율")
    w("   정밀도 = 상위 k개 중 관련 문서 비율의 평균")
    w("")

    # ── 2) 점수 분포로 임계값 결정
    w("=== ② 점수 분포 (임계값 결정 근거) ===")
    pos, neg = [], []
    for q in targets:
        cand = age_filter(docs, q.get("age_months"))
        for s, d in bm.search(q["question"], cand, top_k=20):
            (pos if is_hit(d, q) else neg).append(s)
    pos.sort(); neg.sort()

    def pct(a, p):
        return a[int(len(a) * p)] if a else 0.0

    if pos and neg:
        w("   관련 문서   n=%-4d  min %.2f / 10%% %.2f / 중앙 %.2f / 90%% %.2f / max %.2f"
          % (len(pos), pos[0], pct(pos, .1), pct(pos, .5), pct(pos, .9), pos[-1]))
        w("   무관 문서   n=%-4d  min %.2f / 10%% %.2f / 중앙 %.2f / 90%% %.2f / max %.2f"
          % (len(neg), neg[0], pct(neg, .1), pct(neg, .5), pct(neg, .9), neg[-1]))
        w("")
        best, best_f1 = None, -1
        for t in [round(x * 0.5, 1) for x in range(0, 40)]:
            tp = sum(1 for s in pos if s >= t)
            fp = sum(1 for s in neg if s >= t)
            fn = len(pos) - tp
            if tp == 0:
                continue
            p, r = tp / (tp + fp), tp / (tp + fn)
            f1 = 2 * p * r / (p + r)
            if f1 > best_f1:
                best, best_f1 = (t, p, r, f1), f1
        if best:
            w("   F1 최적 임계값: %.1f  (정밀 %.0f%% / 재현 %.0f%% / F1 %.2f)"
              % (best[0], 100 * best[1], 100 * best[2], best[3]))
        w("   → 관련 문서 하위 10%% 지점(%.2f)을 컷으로 잡으면 재현율 90%% 확보" % pct(pos, .1))
    w("")

    # ── 3) 질문별 상세
    w("=== ③ 질문별 검색 결과 (연령 필터 + top_k 5) ===")
    fails = []
    for q in targets:
        cand = age_filter(docs, q.get("age_months"))
        hits = bm.search(q["question"], cand, top_k=5)
        rel = [is_hit(d, q) for _, d in hits]
        mark = "O" if any(rel) else "X"
        if not any(rel):
            fails.append(q)
        w("")
        w(" [%s] %s  %s" % (q["id"], mark, q["question"][:52]))
        w("      의도: %-18s 후보 %d개" % (q["intent"], len(cand)))
        for (s, d), r in zip(hits, rel):
            w("      %s %5.1f [%-22s] %s" % ("*" if r else " ", s, d["type"], d["text"][:62]))

    # ── 4) 폴백 기대 질문
    w("")
    w("=== ④ 폴백(tier 3) 질문 — 검색이 비어야 정상 ===")
    for q in [x for x in qs if x.get("tier") == 3]:
        hits = bm.search(q["question"], None, top_k=3)
        top = hits[0][0] if hits else 0.0
        w("  [%s] %s" % (q["id"], q["question"][:48]))
        w("        최고점 %.1f  %s" % (top, "(임계값 미만이면 폴백 정상)" if top < 8 else "(점수가 높아 오히려 오답 위험)"))
        w("        기대 동작: %s" % q.get("note", ""))

    w("")
    w("=== ⑤ 실패 질문 %d개 ===" % len(fails))
    for q in fails:
        w("  [%s] %s" % (q["id"], q["question"][:56]))

    out.close()
    print(io.open(D("data", "kb", "eval_report.txt"), encoding="utf-8").read()[:1400])


if __name__ == "__main__":
    main()
