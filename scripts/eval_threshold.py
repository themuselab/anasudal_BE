# -*- coding: utf-8 -*-
"""유사도 임계값을 다시 본다 — 판정 기준을 조였으니 이것도 다시 재야 한다.

경위
  "임계값을 두지 않는다" 는 결정의 근거는 "관련·무관 분포의 중앙값 차이가 0.009 라
  자를 수 없다" 였다. 그런데 그 '관련' 이 느슨한 기준(expect_keywords)으로 정해진
  것이었다. 기준을 조이면 분포가 갈라질 수도 있다. 다시 잰다.

무엇을 재나
  ① 관련·무관 점수 분포 (유형만 기준) — 정말 겹치는가
  ② 임계값 후보별로 무엇을 얻고 무엇을 잃는가
  ③ 가장 중요한 것: 임계값을 걸면 근거가 0 건이 되는 질문이 몇 개인가
     0 건이면 tier 3 으로 빠져 "검증된 자료로는 답변드리기 어려워요" 가 나간다.
     무관한 근거 한 조각이 섞이는 것보다 답변이 통째로 막히는 쪽이 부모에게 나쁘다.
"""
import json, io, os, sys, statistics

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
D = lambda *p: os.path.join(BASE, *p)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from eval_strictness import load, make_judges, norm, age_ok

TOP_K = 4                     # 지금 채택값
CUTS = (0.60, 0.65, 0.68, 0.70, 0.72, 0.74, 0.75, 0.78)


def main():
    docs, qs = load()
    judges, _, _ = make_judges(docs, qs)
    judge = dict(judges)["유형만"]
    byid = {d["id"]: d for d in docs}

    vecs = {}
    for l in io.open(D("data", "kb", "kb_vectors.jsonl"), encoding="utf-8"):
        r = json.loads(l)
        if r["id"] in byid:
            vecs[r["id"]] = norm(r["v"])
    qv = json.load(io.open(D("data", "kb", "eval_query_vectors.json"), encoding="utf-8"))
    ids = list(vecs.keys())

    out = io.open(D("data", "kb", "eval_report_threshold.txt"), "w", encoding="utf-8")
    def w(*a):
        line = " ".join(str(z) for z in a)
        out.write(line + "\n")
        print(line)

    # 질문마다 상위 TOP_K 를 뽑고 관련/무관으로 나눈다
    pos, neg, per_q = [], [], []
    for q in qs:
        if q["question"] not in qv:
            continue
        v = norm(qv[q["question"]])
        age = q.get("age_months")
        sc = []
        for i in ids:
            d = byid[i]
            if not age_ok(d, age):
                continue
            sc.append((sum(a * b for a, b in zip(v, vecs[i])), i))
        sc.sort(reverse=True)
        top = [(s, byid[i]) for s, i in sc[:TOP_K]]
        per_q.append((q, top))
        for s, d in top:
            (pos if judge(d, q) else neg).append(s)

    w("유사도 임계값 재측정 — 유형만 기준 · top_k=%d · 질문 %d개" % (TOP_K, len(per_q)))
    w("")

    def stat(name, xs):
        xs = sorted(xs)
        n = len(xs)
        w("   %-6s n=%-4d 최저 %.3f  하위25%% %.3f  중앙 %.3f  상위25%% %.3f  최고 %.3f"
          % (name, n, xs[0], xs[n // 4], statistics.median(xs), xs[3 * n // 4], xs[-1]))

    w("=== ① 점수 분포 ===")
    stat("관련", pos)
    stat("무관", neg)
    w("   중앙값 차이: %.3f" % (statistics.median(pos) - statistics.median(neg)))
    w("")

    w("=== ② 임계값을 걸면 ===")
    w("   %-7s %-12s %-12s %-14s %s" % ("컷", "관련 살림", "무관 거름", "근거0건 질문", "비고"))
    for c in CUTS:
        kept_pos = sum(1 for s in pos if s >= c)
        cut_neg = sum(1 for s in neg if s < c)
        empty = [q for q, top in per_q if not any(s >= c for s, _ in top)]
        # 근거가 남긴 했는데 정답이 잘린 질문
        lost = [q for q, top in per_q
                if any(s >= c for s, _ in top)
                and any(judge(d, q) for _, d in top)
                and not any(s >= c and judge(d, q) for s, d in top)]
        note = []
        if empty:
            note.append("답변 막힘 %d건" % len(empty))
        if lost:
            note.append("정답만 잘림 %d건" % len(lost))
        w("   %-7.2f %-12s %-12s %-14s %s"
          % (c,
             "%d/%d" % (kept_pos, len(pos)),
             "%d/%d" % (cut_neg, len(neg)),
             "%d" % len(empty),
             " · ".join(note) or "-"))
    w("")

    w("=== ③ 컷 0.70 에서 답변이 막히는 질문 ===")
    for q, top in per_q:
        if not any(s >= 0.70 for s, _ in top):
            w("   %-46s 1위 %.3f" % (q["question"][:46], top[0][0]))
    w("")

    w("=== ④ 무관인데 점수가 높은 것 (상위 8) ===")
    hi = sorted(((s, q, d) for q, top in per_q for s, d in top if not judge(d, q)), reverse=True)
    for s, q, d in hi[:8]:
        w("   %.3f  %-26s  질문: %s" % (s, d["type"], q["question"][:34]))
    out.close()


if __name__ == "__main__":
    main()
