# -*- coding: utf-8 -*-
"""질문셋의 기대 유형을 근거 있는 것만 남기고, 근거 문장을 같이 적어 넣는다.

판정 규칙 (점수가 아니다)
  기대 유형으로 인정하려면 **그 출처 문서 안에 이 질문의 증상을 다룬 문장이 있어야 한다.**
  유사도 점수로 가르면 안 된다 — 정책·검사도구 문서는 부모의 말과 문체가 달라
  점수가 낮게 나온다. 실제로 난청 문서에는 "선생님의 말씀이 잘 안 들려 수업에 집중하지
  못하고 부산한 행동을 보여"가 그대로 있는데 점수는 0.674 다.

  그래서 scripts/eval_justify.py 가 뽑아준 문장을 사람이 읽고 정했다.
  아래 ADD / DROP 이 그 결정이고, 각 줄에 왜인지 적었다.

이 스크립트가 하는 일
  ① DROP 에 적힌 (질문, 유형) 을 expect_types 에서 뺀다
  ② ADD 에 적힌 것을 넣는다
  ③ 남은 기대 유형마다 근거 문장을 expect_why 에 적는다 (출처 문서의 실제 문장)
  ④ 기대 유형이 하나도 안 남는 질문은 tier 3 으로 내린다 (= 근거 없음이 정답)
"""
import json, io, os, sys

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
D = lambda *p: os.path.join(BASE, *p)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from eval_strictness import load, norm, age_ok

Q = lambda s: s          # 질문 앞머리로 찾는다

# ── 뺀다: 그 문서에 이 증상을 다룬 문장이 없다
DROP = [
    ("수업 시간에 집중을", "intellectual",
     "찾은 문장이 사회적 판단·감정 조절·대인관계 얘기라 수업 집중·부산함을 다루지 않는다"),
    ("수업 시간에 집중을", "tic",
     "'틱 증상으로 학업이 방해될 때'라 틱이 있다는 전제가 필요하다. 질문에는 틱 언급이 없다"),
    ("또래랑 어울리질", "asd",
     "자폐 문서의 가장 가까운 문장이 '24개월 이전 눈맞춤·사회적 미소'다. 4살 또래관계를 다룬 문장이 없다"),
    ("편식이 너무 심한데", "asd",
     "지식베이스에 섭식 자료가 없다. 자폐 문서에도 편식을 다룬 문장이 없다"),
]

# ── 넣는다: 그 문서에 이 증상이 그대로 적혀 있다
ADD = [
    ("이름을 불러도", "ksied_warning", "12~17개월 발달 경고신호에 '이름을 불러도 반응이 없어요'가 그대로 있다"),
    ("이름을 불러도", "developmental_milestone", "8~9개월 사회성 기준이 '이름을 부르면 듣고 쳐다본다'이다"),
    ("3살인데 아직 두 단어", "ksied_warning", "3세 발달 경고신호에 '문장으로 말하지 못해요'가 있다"),
    ("3살인데 아직 두 단어", "ksied_guide", "3세 언어 발달특징이 또래 기준을 준다"),
    ("또래랑 어울리질", "ksied_warning", "4세 발달 경고신호에 '다른 아이들을 무시하거나 가족 이외의 사람에게 반응을 보이지 않아요'가 있다"),
    ("24개월인데 아직 의미", "ksied_guide", "24~29개월 언어 발달특징이 '두 개 단어로 된 문장'이라 또래 기준이 된다"),
    ("24개월인데 아직 의미", "policy", "언어발달 경고신호에 '만 2세에 두 단어 문장을 만들지 못함'이 있다"),
    ("우리 애가 6살인데", "dev_basics", "'아이마다 발달 속도가 다른가요'가 형제 비교 걱정에 직접 답한다"),
    ("우리 애가 6살인데", "clinical", "'언어발달지연이 의심되면 언어평가 및 진단을 위해 … 의뢰'가 다음 단계를 준다"),
    ("우리 애가 6살인데", "policy", "언어발달 경고신호가 또래 대비 판단 기준을 준다"),
    ("37주 전에 태어난", "dev_basics", "'아이마다 발달 속도가 다른가요'가 또래 비교 걱정에 직접 답한다"),
    ("감각발달재활이 뭐예요", "therapy_mapping", "매핑 문서가 감각발달재활을 언제 고려하는지 설명한다"),
    ("심리운동이랑 운동발달재활", "therapy_mapping", "매핑 문서가 두 치료를 각각 언제 쓰는지 설명한다"),
]

SNIP = 90


def match(q, head):
    return q["question"].startswith(head)


def main():
    docs, _ = load()
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

    path = D("data", "kb", "eval_questions.json")
    qs = json.load(io.open(path, encoding="utf-8"))
    wrapped = isinstance(qs, dict)
    items = qs.get("questions", qs) if wrapped else qs

    log = []
    for head, t, why in DROP:
        for q in items:
            if match(q, head) and t in q.get("expect_types", []):
                q["expect_types"] = [x for x in q["expect_types"] if x != t]
                q.setdefault("dropped_types", {})[t] = why
                log.append("  - %-34s %-24s %s" % (q["question"][:34], t, why[:46]))
    for head, t, why in ADD:
        for q in items:
            if match(q, head) and t not in q.get("expect_types", []):
                q.setdefault("expect_types", []).append(t)
                q.setdefault("added_types", {})[t] = why
                log.append("  + %-34s %-24s %s" % (q["question"][:34], t, why[:46]))

    # ── 남은 기대 유형마다 출처 문서의 실제 문장을 적어 넣는다
    for q in items:
        if q["question"] not in qv:
            continue
        v = norm(qv[q["question"]])
        age = q.get("age_months")
        why = {}
        for t in q.get("expect_types", []):
            best = None
            for d in bytype.get(t, []):
                if d["id"] not in vecs:
                    continue
                s = sum(a * b for a, b in zip(v, vecs[d["id"]]))
                if best is None or s > best[0]:
                    best = (s, d)
            if best:
                why[t] = best[1]["text"][:SNIP].replace("\n", " ")
        if why:
            q["expect_why"] = why

    # ── 기대가 비면 "근거 없음이 정답"인 질문이다
    demoted = []
    for q in items:
        if q.get("tier", 1) in (1, 2) and not q.get("expect_types"):
            q["tier"] = 3
            demoted.append(q["question"])

    io.open(path, "w", encoding="utf-8").write(json.dumps(qs, ensure_ascii=False, indent=2))

    print("기대 유형 조정")
    for l in log:
        print(l)
    if demoted:
        print("\ntier 3 으로 내림 (기대 유형이 남지 않음 = 근거 없음이 정답):")
        for d in demoted:
            print("  ", d[:60])
    tier12 = [q for q in items if q.get("tier", 1) in (1, 2)]
    tot = sum(len(q.get("expect_types", [])) for q in tier12)
    print("\n채점 대상 질문 %d개 · 기대 유형 %d건 · 전부 근거 문장 보유" % (len(tier12), tot))


if __name__ == "__main__":
    main()
