# -*- coding: utf-8 -*-
"""질문은 어디서 왔나 — 평가 질문 30개의 출처를 추적한다.

왜 필요한가
  기대 유형에 근거를 붙이고 나니(15번) 사슬이 한 칸 남는다. **질문 자체**는 팀이 썼다.
  "이 질문으로 시험했으니 우리 서비스는 근거가 있다"고 말하려면, 그 질문이 어디서
  왔는지 답할 수 있어야 한다.

무엇을 답할 수 있나
  질문마다 **그 걱정이 정부 문서에 실제로 실려 있는지** 찾는다. 예를 들어
  "이름을 불러도 잘 안 돌아봐요"는 K-DST 12~17개월 경고신호에 "이름을 불러도 반응이
  없어요"로 그대로 있다. 즉 이 질문은 지어낸 상황이 아니라 **국가가 경고신호로 지정한
  항목을 부모의 말로 옮긴 것**이다.

무엇을 답할 수 없나
  실제 부모가 무엇을 어떤 비율로 묻는지는 모른다. 질문 30개가 현실 분포를 대표한다는
  근거는 없다. 이건 문서에 그대로 적는다.

출력
  backend/docs/eval-question-origin.md
"""
import json, io, os, sys, collections

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
D = lambda *p: os.path.join(BASE, *p)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from eval_strictness import load, norm, age_ok

# 질문의 걱정이 '문서에 실린 항목'임을 가장 잘 보여주는 유형부터 본다.
# 경고신호·증상 목록이 먼저고, 그 다음이 발달 기준, 제도·검사도구 순이다.
PREF = ["ksied_warning", "red_flag", "milestone_lang",
        "asd", "hearing", "tic", "vision", "cp", "ds", "intellectual", "growth",
        "developmental_milestone", "ksied_guide", "dev_basics",
        "policy", "screening", "assessment_tool", "clinical",
        "therapy_area", "therapy_mapping", "parent_tip"]

# 설계 의도를 사람 말로. intent 코드만 두면 "왜 이 질문인가"가 안 보인다.
PURPOSE = {
    "발달우려":   "부모가 실제로 걱정을 들고 오는 형태",
    "감별":       "한 증상에 원인이 둘 이상 — 하나로 단정하면 안 되는 사례",
    "제도":       "검색이 아니라 제도 문서를 정확히 읽어야 하는 질문",
    "치료시기":   "시기를 잘못 말하면 부모가 손해를 보는 질문",
    "치료판단":   "치료할지 지켜볼지 — 문서의 기준 없이 답하면 안 되는 질문",
    "부모대처":   "진단이 아니라 오늘 할 일을 묻는 질문",
    "용어설명":   "치료영역 이름을 모르는 부모가 첫 화면에서 묻는 것",
    "검사도구":   "결과지를 받아 들고 오는 상황",
    "대체요법":   "맘카페 정보에 근거로 답해야 하는 사례",
    "예후":       "예후를 묻는 질문 — 단정도 회피도 안 되는 자리",
    "발달경과":   "진단명을 이미 아는 부모의 다음 질문",
    "기관매칭":   "RAG 가 아니라 DB 질의로 가야 하는 것",
    "범위밖":     "자료가 없을 때 지어내지 않는지 보는 시험",
    "위험":       "진단 요구 — 검색 전에 막혀야 하는 시험",
}


def purpose_of(intent):
    head = intent.split("_")[0]
    return PURPOSE.get(head, "")


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

    qs = json.load(io.open(D("data", "kb", "eval_questions.json"), encoding="utf-8"))
    if isinstance(qs, dict):
        qs = qs.get("questions", qs)

    def anchor(q):
        """이 질문의 걱정이 실려 있는 문서의 문장 — 경고신호·증상 목록을 먼저 본다"""
        if q["question"] not in qv:
            return None
        v = norm(qv[q["question"]])
        age = q.get("age_months")
        types = q.get("expect_types", [])
        for t in sorted(types, key=lambda x: PREF.index(x) if x in PREF else 99):
            best = None
            for d in bytype.get(t, []):
                if d["id"] not in vecs or not age_ok(d, age):
                    continue
                s = sum(a * b for a, b in zip(v, vecs[d["id"]]))
                if best is None or s > best[0]:
                    best = (s, d)
            if best:
                return best[1]
        return None

    out = io.open(D("backend", "docs", "eval-question-origin.md"), "w", encoding="utf-8")
    w = lambda *a: out.write(" ".join(str(z) for z in a) + "\n")

    w("# 어떤 질문으로 시험했고, 그 질문은 어디서 왔나")
    w("")
    w("평가 질문 %d개의 출처다. 기대 정답의 근거는 [eval-question-basis.md](./eval-question-basis.md) 에," % len(qs))
    w("튜닝 경위는 [rag-tuning.md](./rag-tuning.md) 15번에 있다.")
    w("")
    w("## 먼저 분명히 할 것")
    w("")
    w("**질문은 팀이 썼다.** 부모에게서 수집한 것이 아니다. 대신 두 가지는 말할 수 있다.")
    w("")
    w("1. 아무거나 쓰지 않았다 — 무엇을 시험할지 정하고 칸을 채웠다 (아래 커버리지)")
    w("2. 대부분의 질문은 **국가 문서가 경고신호·증상으로 지정한 항목**을 부모의 말로 옮긴 것이다")
    w("")
    w("**말할 수 없는 것**: 실제 부모가 무엇을 어떤 비율로 묻는지. 이 %d개가 현실 분포를" % len(qs))
    w("대표한다는 근거는 없다. 그건 서비스를 열어 실제 질문이 쌓여야 알 수 있다.")
    w("")

    # ── 커버리지
    w("## 무엇을 시험하려고 넣었나")
    w("")
    groups = collections.OrderedDict()
    for q in qs:
        groups.setdefault(q["intent"].split("_")[0], []).append(q)
    w("| 갈래 | 문항 | 왜 이 칸이 필요한가 |")
    w("|---|---|---|")
    for head, items in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        w("| %s | %d | %s |" % (head, len(items), purpose_of(items[0]["intent"]) or "—"))
    w("")
    w("마지막 네 갈래(기관매칭·범위밖·위험)는 **답을 맞히는 시험이 아니라 안 하는지 보는 시험**이다.")
    w("자료가 없을 때 지어내는지, 진단 요구를 검색 전에 막는지를 본다. 이 %d개는 tier 3 으로"
      % len([q for q in qs if q.get("tier", 1) == 3]))
    w("두어 적중률 계산에서 뺀다 — 근거가 안 나오는 것이 정답이라 같이 세면 숫자가 뒤집힌다.")
    w("")

    # ── 질문별 출처
    w("## 질문별 — 이 걱정이 문서에 실려 있는가")
    w("")
    w("| # | 질문 | 이 걱정이 실린 곳 | 문서의 문장 |")
    w("|---|---|---|---|")
    traced = 0
    for q in qs:
        d = anchor(q)
        qt = q["question"].replace("|", "\\|")
        if d is None:
            w("| %s | %s | — | *문서에 없음 — 그것이 시험 내용이다* |" % (q["id"], qt))
            continue
        traced += 1
        src = d.get("source", "?")
        src = src.split(" — ")[0][:30]
        w("| %s | %s | %s | %s |" % (q["id"], qt, src,
                                     d["text"][:80].replace("|", "\\|").replace("\n", " ")))
    w("")
    w("추적된 질문 %d / %d. 나머지는 자료가 없는 것이 정답인 시험 문항이다." % (traced, len(qs)))
    w("")
    w("생성: `scripts/eval_question_origin.py`")
    out.close()

    print("질문 %d개 · 문서 항목으로 추적됨 %d개" % (len(qs), traced))
    print("→ backend/docs/eval-question-origin.md")


if __name__ == "__main__":
    main()
