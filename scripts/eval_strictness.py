# -*- coding: utf-8 -*-
"""판정 기준을 조였을 때 숫자가 얼마나 내려가는지 잰다.

왜 이걸 따로 재나
  기존 하네스의 is_hit 은 `expect_types` 와 `expect_keywords` 의 OR 이다.
  키워드 규칙이 문제였다 — Q14 의 "발달" 두 글자가 1,496 청크 중 1,265 개(85%)에
  들어 있어서, 그 질문은 무엇을 물어와도 적중으로 세어진다.

  키워드는 팀이 손으로 적은 것이라 "왜 그게 정답이냐"에 답할 근거가 없다.
  반면 `type` 은 청크가 어느 출처 문서에서 나왔는지와 1:1 이다
  (asd = 질병관리청 자폐스펙트럼장애 문서, tic = 틱장애 문서 …).
  유형만으로 판정하면 "이 질문에는 질병관리청 ○○ 문서가 나와야 한다" 가 되고,
  그건 의학 판단이 아니라 출처 지정이라 전문가가 아니어도 말할 수 있다.

세 기준
  현재    type OR keyword            — 지금 문서에 실린 숫자
  정제    type OR 드문 keyword        — 흔한 키워드(기본 3% 초과)만 버린다
  유형만  type                        — 팀이 판단한 부분을 전부 뺀다

BM25 와 임베딩 둘 다 같은 기준으로 재야 "개선폭"을 말할 수 있다.
임베딩은 data/kb/kb_vectors.jsonl 과 eval_query_vectors.json 캐시를 쓴다 (API 호출 없음).
"""
import json, io, os, math, sys

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
D = lambda *p: os.path.join(BASE, *p)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from eval_retrieval import BM25, age_filter        # 토크나이저·점수 함수를 그대로 쓴다

COMMON_PCT = 3.0      # 이 비율 넘게 등장하는 키워드는 "흔하다"고 본다
KS = (1, 3, 5, 10)


def norm(v):
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def age_ok(doc, age):
    m = doc.get("meta", {})
    lo, hi = m.get("age_lo"), m.get("age_hi")
    if lo is None or hi is None or age is None:
        return True
    return lo <= age <= hi or (age > 71 and hi >= 60)


def load():
    docs = [json.loads(l) for l in io.open(D("data", "kb", "kb_chunks.jsonl"), encoding="utf-8") if l.strip()]
    qs = json.load(io.open(D("data", "kb", "eval_questions.json"), encoding="utf-8"))
    if isinstance(qs, dict):
        qs = qs.get("questions", qs)
    targets = [q for q in qs if q.get("tier", 1) in (1, 2)]
    return docs, targets


def keyword_freq(docs, qs):
    """키워드마다 몇 개 청크에 들어 있는지"""
    kws = sorted({k for q in qs for k in q.get("expect_keywords", [])})
    return {k: sum(1 for d in docs if k in d["text"]) for k in kws}


def make_judges(docs, qs):
    n = len(docs)
    freq = keyword_freq(docs, qs)
    cut = n * COMMON_PCT / 100.0
    rare = {k for k, c in freq.items() if c <= cut}

    def current(doc, q):
        if q.get("expect_types") and doc["type"] in q["expect_types"]:
            return True
        return any(k in doc["text"] for k in q.get("expect_keywords", []))

    def refined(doc, q):
        if q.get("expect_types") and doc["type"] in q["expect_types"]:
            return True
        return any(k in doc["text"] for k in q.get("expect_keywords", []) if k in rare)

    def types_only(doc, q):
        return bool(q.get("expect_types")) and doc["type"] in q["expect_types"]

    dropped = sorted(((c, k) for k, c in freq.items() if c > cut), reverse=True)
    return [("현재", current), ("정제", refined), ("유형만", types_only)], dropped, freq


def score(searcher, qs, judge, k, use_filter):
    """적중 = 상위 k 안에 정답 1건 이상 / 정밀 = 상위 k 중 정답 비율의 평균"""
    hit = prec = 0.0
    for q in qs:
        got = searcher(q, k, use_filter)
        rel = [1 if judge(d, q) else 0 for d in got]
        hit += 1.0 if any(rel) else 0.0
        prec += (sum(rel) / len(rel)) if rel else 0.0
    n = len(qs)
    return 100.0 * hit / n, 100.0 * prec / n


def main():
    docs, qs = load()
    judges, dropped, freq = make_judges(docs, qs)
    n = len(docs)

    out = io.open(D("data", "kb", "eval_report_strictness.txt"), "w", encoding="utf-8")
    def w(*a):
        line = " ".join(str(z) for z in a)
        out.write(line + "\n")
        print(line)

    w("판정 기준을 조였을 때 — 청크 %d개 / 질문 %d개" % (n, len(qs)))
    w("")
    w("=== 버리는 키워드 (청크의 %.0f%% 초과에 등장) ===" % COMMON_PCT)
    for c, k in dropped:
        w("   %-12s %5d건  %5.1f%%" % (k, c, 100.0 * c / n))
    w("   버린 키워드 %d종 / 전체 %d종" % (len(dropped), len(freq)))
    w("")

    # ── BM25
    bm = BM25(docs)
    def bm_search(q, k, use_filter):
        cand = age_filter(docs, q.get("age_months")) if use_filter else None
        return [d for _, d in bm.search(q["question"], cand, top_k=k)]

    # ── 임베딩 (캐시된 벡터만 쓴다)
    emb_search = None
    try:
        vecs = {}
        for l in io.open(D("data", "kb", "kb_vectors.jsonl"), encoding="utf-8"):
            r = json.loads(l)
            vecs[r["id"]] = norm(r["v"])
        byid = {d["id"]: d for d in docs}
        qv = json.load(io.open(D("data", "kb", "eval_query_vectors.json"), encoding="utf-8"))
        ids = [i for i in vecs if i in byid]
        missing = [q["question"] for q in qs if q["question"] not in qv]
        if missing:
            w("   ※ 질의 벡터 캐시에 없는 질문 %d개 — 임베딩 표는 건너뜀" % len(missing))
        else:
            def emb_search(q, k, use_filter):
                v = norm(qv[q["question"]])
                age = q.get("age_months")
                sc = []
                for i in ids:
                    d = byid[i]
                    if use_filter and not age_ok(d, age):
                        continue
                    sc.append((sum(a * b for a, b in zip(v, vecs[i])), i))
                sc.sort(reverse=True)
                return [byid[i] for _, i in sc[:k]]
            w("   임베딩 벡터 %d / %d 청크" % (len(ids), n))
    except (IOError, OSError, ValueError) as e:
        w("   ※ 임베딩 캐시를 못 읽음 (%s) — BM25 만 잰다" % type(e).__name__)

    w("")
    for name, searcher in (("BM25", bm_search), ("임베딩", emb_search)):
        if searcher is None:
            continue
        w("=== %s · 연령 필터 적용 ===" % name)
        w("   %-5s %s" % ("k", "".join("%-22s" % ("[%s]" % j) for j, _ in judges)))
        for k in KS:
            cells = []
            for _, judge in judges:
                h, p = score(searcher, qs, judge, k, True)
                cells.append("적중 %3.0f%% 정밀 %3.0f%%" % (h, p))
            w("   %-5d %s" % (k, "".join("%-22s" % c for c in cells)))
        w("")

    # ── 채택값(k=3)에서 BM25 대비 개선폭
    if emb_search is not None:
        w("=== k=3 에서 BM25 → 임베딩 개선폭 ===")
        for name, judge in judges:
            bh, bp = score(bm_search, qs, judge, 3, True)
            eh, ep = score(emb_search, qs, judge, 3, True)
            w("   [%-6s] 적중 %3.0f%% → %3.0f%% (%+.0f%%p)   정밀 %3.0f%% → %3.0f%% (%+.0f%%p)"
              % (name, bh, eh, eh - bh, bp, ep, ep - bp))
        w("")

    w("적중률 = 상위 k개 안에 관련 문서가 1개라도 있는 질문 비율")
    w("정밀도 = 상위 k개 중 관련 문서 비율의 평균")
    out.close()


if __name__ == "__main__":
    main()
