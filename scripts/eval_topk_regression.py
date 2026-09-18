# -*- coding: utf-8 -*-
"""top_k 를 다시 정한다 — 판정 기준을 조이면 k=3 의 근거가 사라지기 때문.

경위
  처음 k=3 을 고른 이유는 "k=3 에서 적중이 천장에 닿고 그 위는 정밀만 깎인다" 였다.
  그런데 그 천장은 느슨한 판정 기준(expect_keywords)이 만든 것이었다.
  "발달" 두 글자가 1,496 청크 중 1,265 개에 들어 있어서, 그 질문은 k=1 에서도 적중이었다.

  키워드를 걷어내고 유형(= 출처 문서)만으로 판정하면 적중이 k=5 까지 계속 오른다.
  그러면 k=3 은 더 이상 "천장에서 끊은 값"이 아니다. 다시 정해야 한다.

무엇을 재나
  ① k 별 적중·정밀 (1~10), 판정 기준 3종
  ② k 를 늘렸을 때 어느 질문이 살아나는가 — 한 건씩 이름을 적는다
  ③ 늘어난 근거가 어떤 점수대인가 — 4·5위가 1위와 얼마나 차이 나는지
  ④ 프롬프트에 들어가는 글자 수 — k 를 늘리면 생성이 읽어야 할 양이 늘어난다

무엇을 못 재나
  근거가 늘었을 때 답변 품질이 어떻게 되는지는 여기서 안 나온다.
  그건 생성을 돌려봐야 하고, 무료 티어 하루 20건으로는 27문항 × k 2종을 못 돌린다.
  검색 쪽 숫자만 내고, 생성 쪽은 판단 근거를 따로 적는다.
"""
import json, io, os, math, sys

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
D = lambda *p: os.path.join(BASE, *p)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from eval_strictness import load, make_judges, norm, age_ok

KS = (1, 2, 3, 4, 5, 6, 8, 10)


def main():
    docs, qs = load()
    judges, dropped, _ = make_judges(docs, qs)
    byid = {d["id"]: d for d in docs}

    vecs = {}
    for l in io.open(D("data", "kb", "kb_vectors.jsonl"), encoding="utf-8"):
        r = json.loads(l)
        if r["id"] in byid:
            vecs[r["id"]] = norm(r["v"])
    qv = json.load(io.open(D("data", "kb", "eval_query_vectors.json"), encoding="utf-8"))
    ids = list(vecs.keys())

    missing = [q["question"] for q in qs if q["question"] not in qv]
    if missing:
        print("질의 벡터 캐시에 없는 질문 %d개 — 먼저 eval_embedding.py 를 돌려야 한다" % len(missing))
        return

    def ranked(q, use_filter=True):
        """이 질문에 대한 전체 순위 (점수, 청크)"""
        v = norm(qv[q["question"]])
        age = q.get("age_months")
        sc = []
        for i in ids:
            d = byid[i]
            if use_filter and not age_ok(d, age):
                continue
            sc.append((sum(a * b for a, b in zip(v, vecs[i])), i))
        sc.sort(reverse=True)
        return [(s, byid[i]) for s, i in sc[:12]]

    order = {q["question"]: ranked(q) for q in qs}       # 한 번만 계산한다

    out = io.open(D("data", "kb", "eval_report_topk.txt"), "w", encoding="utf-8")
    def w(*a):
        line = " ".join(str(z) for z in a)
        out.write(line + "\n")
        print(line)

    w("top_k 회귀 — 임베딩 · 연령 필터 적용 · 질문 %d개 · 청크 %d개" % (len(qs), len(docs)))
    w("")

    # ── ① k 별 성능
    w("=== ① k 별 적중 / 정밀 ===")
    w("   %-4s %s" % ("k", "".join("%-22s" % ("[%s]" % n) for n, _ in judges)))
    for k in KS:
        cells = []
        for _, judge in judges:
            hit = prec = 0.0
            for q in qs:
                rel = [1 if judge(d, q) else 0 for _, d in order[q["question"]][:k]]
                hit += 1.0 if any(rel) else 0.0
                prec += sum(rel) / len(rel) if rel else 0.0
            cells.append("적중 %3.0f%% 정밀 %3.0f%%" % (100 * hit / len(qs), 100 * prec / len(qs)))
        w("   %-4d %s" % (k, "".join("%-22s" % c for c in cells)))
    w("")

    # ── ② 어느 질문이 살아나는가 (유형만 기준)
    strict = dict(judges)["유형만"]
    w("=== ② k 를 늘리면 살아나는 질문 (유형만 기준) ===")
    first = {}
    for q in qs:
        hitrank = None
        for i, (s, d) in enumerate(order[q["question"]], 1):
            if strict(d, q):
                hitrank = i
                break
        first[q["question"]] = hitrank
    for k in KS:
        new = [q for q in qs if first[q["question"]] == k]
        if not new:
            continue
        w("   k=%-3d +%d건" % (k, len(new)))
        for q in new:
            s, d = order[q["question"]][k - 1]
            w("        %-44s  %s  %.3f" % (q["question"][:44], d["type"], s))
    never = [q for q in qs if first[q["question"]] is None]
    if never:
        w("   12위 안에 없음 %d건" % len(never))
        for q in never:
            w("        %-44s  (기대 %s)" % (q["question"][:44], ",".join(q.get("expect_types", [])) or "-"))
    w("")

    # ── ③ 4·5위가 어떤 점수대인가
    w("=== ③ 순위별 평균 유사도 — 뒤로 갈수록 얼마나 떨어지나 ===")
    for r in range(1, 9):
        vals = [order[q["question"]][r - 1][0] for q in qs if len(order[q["question"]]) >= r]
        rel = [1 for q in qs if len(order[q["question"]]) >= r and strict(order[q["question"]][r - 1][1], q)]
        w("   %d위  평균 %.3f   이 자리가 정답인 질문 %d/%d" % (r, sum(vals) / len(vals), len(rel), len(qs)))
    w("")

    # ── ④ 프롬프트에 들어가는 양
    w("=== ④ 근거로 넘기는 글자 수 (질문당 평균) ===")
    for k in (3, 5):
        tot = sum(sum(len(d["text"]) for _, d in order[q["question"]][:k]) for q in qs)
        w("   k=%d  평균 %d자" % (k, tot // len(qs)))
    w("")
    w("적중률 = 상위 k개 안에 관련 문서가 1개라도 있는 질문 비율")
    w("정밀도 = 상위 k개 중 관련 문서 비율의 평균")
    out.close()


if __name__ == "__main__":
    main()
