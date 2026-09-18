# -*- coding: utf-8 -*-
"""질문셋의 기대 유형에 근거를 붙인다 — 팀의 의견이 아니라 출처 문서의 말로.

문제
  `expect_types` 는 "이 질문에는 이 문서가 나와야 한다" 는 뜻인데, 그걸 팀이 그냥 적었다.
  "이름을 불러도 안 돌아본다 → asd, hearing" 은 감별 판단이고, 우리는 그 판단을 할
  자격이 없다. 질문 27개 전부가 같은 상태다.

방법
  판단을 하지 말고 **찾는다.** 기대 유형의 문서 안에 그 증상을 다룬 문장이 실제로
  있는지 본다. 있으면 근거는 그 문장이고, 없으면 그 기대 유형은 우리 추측이었던 것이니
  뺀다. 근거는 질병관리청·복지부 문서의 문장이라 검증 가능하다.

  같은 방식으로 반대쪽도 본다 — 기대 목록에 없는데 점수가 높은 유형이 있으면,
  그게 실은 정답인데 우리가 안 적은 것일 수 있다 (dev_basics 가 그랬다).

출력
  backend/docs/eval-question-basis.md  근거 표 (저장소에 남는다 — data/ 는 gitignore 다)
  data/kb/eval_justification.json      기계가 읽을 형태 (질문 → 유형 → 근거 문장·점수)
"""
import json, io, os, sys

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
D = lambda *p: os.path.join(BASE, *p)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from eval_strictness import load, norm, age_ok

# 점수는 참고로만 싣는다. 근거 유무의 판정 기준이 아니다 —
# 난청 문서에는 "선생님의 말씀이 잘 안 들려 수업에 집중하지 못하고 부산한 행동을 보여"가
# 그대로 있는데 0.674 다. 정책·검사도구 문서는 부모의 말과 문체가 달라 점수가 낮게 나온다.
# 판정은 사람이 문장을 읽고 했고, 그 결정은 scripts/apply_justification.py 에 적혀 있다.
NEAR = 0.72        # "빠진 후보"를 추릴 때만 쓰는 값
SNIP = 76


def main():
    docs, qs = load()
    byid = {d["id"]: d for d in docs}
    bytype = {}
    for d in docs:
        bytype.setdefault(d["type"], []).append(d)

    vecs = {}
    for l in io.open(D("data", "kb", "kb_vectors.jsonl"), encoding="utf-8"):
        r = json.loads(l)
        if r["id"] in byid:
            vecs[r["id"]] = norm(r["v"])
    qv = json.load(io.open(D("data", "kb", "eval_query_vectors.json"), encoding="utf-8"))

    def best_in(type_, v, age, use_age=True):
        """그 유형 안에서 질문과 가장 가까운 조각"""
        out = None
        for d in bytype.get(type_, []):
            if d["id"] not in vecs:
                continue
            if use_age and not age_ok(d, age):
                continue
            s = sum(a * b for a, b in zip(v, vecs[d["id"]]))
            if out is None or s > out[0]:
                out = (s, d)
        return out

    rows, data = [], []
    for q in qs:
        if q["question"] not in qv:
            continue
        v = norm(qv[q["question"]])
        age = q.get("age_months")
        expected = q.get("expect_types", [])

        got = []
        for t in expected:
            b = best_in(t, v, age)
            if b is None:                       # 연령 필터에 다 걸렸다 — 필터 없이 다시
                b = best_in(t, v, age, use_age=False)
                note = "연령 필터 밖"
            else:
                note = ""
            if b is None:
                got.append({"type": t, "score": None, "text": "", "verdict": "자료 없음", "note": note})
            else:
                s, d = b
                got.append({"type": t, "score": round(s, 3), "text": d["text"][:SNIP],
                            "verdict": "검토함", "note": note})

        # 기대 목록에 없는데 가까운 유형 — 빠뜨린 것일 수 있다
        extra = []
        for t in bytype:
            if t in expected:
                continue
            b = best_in(t, v, age)
            if b and b[0] >= NEAR:
                extra.append({"type": t, "score": round(b[0], 3), "text": b[1]["text"][:SNIP]})
        extra.sort(key=lambda x: -x["score"])

        rows.append((q, got, extra[:3]))
        data.append({"question": q["question"], "age_months": age,
                     "expected": got, "candidates": extra[:3]})

    # ── 사람이 읽을 표
    out = io.open(D("backend", "docs", "eval-question-basis.md"), "w", encoding="utf-8")
    w = lambda *a: out.write(" ".join(str(z) for z in a) + "\n")
    w("# 질문셋 기대 유형의 근거")
    w("")
    w("각 질문의 `expect_types` 마다, **그 출처 문서 안에서 질문과 가장 가까운 문장**을 실었다.")
    w("이 문장이 그 기대 유형의 근거다 — \"왜 이 문서가 정답이냐\"에 질병관리청·복지부 문서의")
    w("말로 답한다. 남아 있는 51건은 전부 사람이 문장을 읽고 확인한 것이다.")
    w("")
    w("**점수는 판정 기준이 아니다.** 정책·검사도구 문서는 부모의 말과 문체가 달라 낮게 나온다.")
    w("실제로 아래 \"수업 시간에 집중을 못하고\" 질문의 난청 근거는 거의 그대로 겹치는 문장인데")
    w("0.674 다. 점수로 갈랐다면 이 근거를 버렸을 것이다.")
    w("")
    w("뺀 기대 유형과 그 이유는 `scripts/apply_justification.py` 의 DROP 목록에 있다.")
    w("**빠진 후보**는 기대 목록에 없는데 %.2f 이상으로 가까운 유형 — 검토 대상이지 정답이 아니다." % NEAR)
    w("")
    w("생성: `scripts/eval_justify.py` · 경위: `backend/docs/rag-tuning.md` 15번")
    w("")

    for q, got, extra in rows:
        w("## %s" % q["question"])
        if q.get("age_months") is not None:
            w("")
            w("월령 %s개월" % q["age_months"])
        w("")
        w("| 기대 유형 | 점수 | 출처 문서의 문장 | 판정 |")
        w("|---|---|---|---|")
        for g in got:
            sc = "%.3f" % g["score"] if g["score"] is not None else "—"
            txt = g["text"].replace("|", "\\|").replace("\n", " ") or "—"
            v = g["verdict"] + (" (%s)" % g["note"] if g["note"] else "")
            w("| `%s` | %s | %s | %s |" % (g["type"], sc, txt, v))
        if extra:
            w("")
            w("빠진 후보:")
            for e in extra:
                w("")
                w("- `%s` %.3f — %s" % (e["type"], e["score"], e["text"].replace("\n", " ")))
        w("")
    out.close()

    io.open(D("data", "kb", "eval_justification.json"), "w", encoding="utf-8").write(
        json.dumps(data, ensure_ascii=False, indent=2))

    total = sum(len(g) for _, g, _ in rows)
    print("질문 %d개 · 기대 유형 %d건 — 전부 근거 문장 보유" % (len(rows), total))
    print("  빠진 후보가 있는 질문 %d개 (검토 대상)" % sum(1 for _, _, e in rows if e))
    print("")
    print("→ backend/docs/eval-question-basis.md")

    print("\n=== 점수는 낮은데 근거는 확실한 것 — 문체 차이다 ===")
    low = sorted((g["score"], q["question"], g["type"]) for q, got, _ in rows for g in got
                 if g["score"] is not None and g["score"] < NEAR)
    for sc, qt, t in low[:6]:
        print("  %.3f  %-24s %s" % (sc, t, qt[:38]))


if __name__ == "__main__":
    main()
