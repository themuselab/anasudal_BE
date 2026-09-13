# -*- coding: utf-8 -*-
"""정상 소아의 성장 KB (국가건강정보포털 cntnts_sn=5799)
서비스 관련성이 높은 항목만 선별:
  - 미숙아 교정연령 규칙 (K-DST 연령 매칭 로직에 직접 영향)
  - 머리둘레 성장 이상 -> 뇌 발달 문제 신호
  - 저신장 정상변이 (부모가 '또래보다 작다'고 물을 때 근거)
"""
import csv, io, os, json, collections

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
D = lambda *p: os.path.join(BASE, *p)
SRC = "질병관리청 국가건강정보포털 — 정상 소아의 성장"

GROWTH_RULE = [
    ("미숙아 교정연령",
     "임신기간 37주 이전에 태어난 미숙아는 성장 상태를 판단할 때 만 2세까지는 실제 출생일이 아닌 출생예정일(분만예정일)을 기준으로 판단해야 함. 그렇지 않으면 정상적으로 성장하고 있는 미숙아를 성장부진아로 잘못 판단하게 됨"),
    ("성장 개인차",
     "전체 소아기에 걸쳐 항상 똑같은 속도로 성장하는 아이는 없음. 정상적으로 성장하는 소아도 몇 주에서 몇 달간 성장이 더 느린 시기와 더 잘 크는 시기가 있음. 어느 한 시점에 또래 아이들과 단순 비교하여 성장 상태를 판단하는 것은 적절치 못함"),
    ("유전 반영 시기",
     "부모의 체격에 의한 유전적 영향이 나타나는 시기는 2세 전후. 2세 이후에는 대부분의 정상 소아가 자신의 성장 수준을 크게 벗어나지 않고 그 수준을 지키며 성장. 2세 이후에 그동안 지켜오던 성장 수준을 이탈하면 병적인 원인이 있을 가능성"),
    ("성장속도 관찰 기간",
     "2세 이상의 소아에서 성장속도를 알려면 최소한 6개월 이상의 관찰기간이 필요"),
]

HEIGHT = [
    ("0~6개월", "월 2.5센티미터"),
    ("7~12개월", "월 1.25센티미터"),
    ("12~24개월", "연 10센티미터 이상"),
    ("24~36개월", "연 8센티미터"),
    ("36~48개월", "연 7센티미터"),
    ("4~10세", "연 5~6센티미터"),
]

WEIGHT = [
    ("생후 첫 3개월", "하루 약 30그램 증가"),
    ("생후 3~6개월", "하루 약 20그램 증가"),
    ("생후 6~12개월", "하루 약 10그램 증가"),
    ("2세~사춘기 전", "연 2킬로그램 정도 증가"),
    ("신생아 초기", "생후 첫 수일간 체중이 감소할 수 있으나 감소 정도가 10퍼센트를 넘지는 않으며 생후 10~14일이면 출생체중으로 회복"),
]

HEAD = [
    ("머리둘레 의미", "머리둘레의 성장은 뇌의 성장을 반영함"),
    ("정상 성장", "출생 시 평균 34센티미터. 생후 첫 1년 동안 한 달에 1센티미터씩 증가하며 첫 6개월에 가장 빨리 성장. 12개월에 약 46센티미터가 되고 대부분의 머리둘레 성장은 4세가 되면 거의 마무리"),
    ("경고 - 과속 성장", "머리둘레가 너무 빠르게 커지면 수두증, 뇌종양 혹은 기타 대두증을 일으키는 다른 질병의 증상일 수 있음"),
    ("경고 - 저속 성장", "머리둘레의 성장이 너무 느리면 뇌 발달에 문제가 있거나 머리뼈의 봉합선이 비정상적으로 일찍 닫히는 병을 생각해봐야 함"),
    ("경고 - 관찰 시기", "생후 첫 18개월, 특히 첫 12개월 동안 머리둘레 성장에 이상이 있으면 면밀한 관찰이 필요"),
    ("경고 - 즉시 진료", "머리뼈들 사이 간격이 비정상적으로 멀어져 손으로 만져지거나, 앞숫구멍이 볼록 올라오는 증상이 함께 있으면 반드시 의사와 상의. 머리나 얼굴 피부에 유난히 굵은 혈관이 많이 보이거나 봉합선 부위가 붉거나 부어오르거나 분비물이 있는 경우도 마찬가지"),
]

SHORT_STATURE = [
    ("정상변이 안내", "성장이 잘 안되어 키가 작다고 의사를 찾는 소아의 대부분은 병적인 원인 질환이 없는 체질성 성장지연이나 가족성 저신장과 같은 정상변이의 저신장"),
    ("체질성 성장지연", "3세경 및 11~12세경에 일시적으로 성장이 늦어지는 시기가 있으며 키 나이와 뼈 나이가 실제 나이보다 2~4년 정도 늦음. 사춘기 시작도 2~3년 늦어 이차 성징이 늦게 나타나지만 사춘기 말기에 급속성장이 일어나 결국 정상적인 키를 가진 성인으로 성장"),
    ("가족성 저신장", "부모의 키가 모두 작은 경우로 뼈나이는 실제 나이에 맞게 진행되고 키나이는 실제나이보다 낮음. 성장속도는 정상이나 성인키는 일반적으로 작음"),
    ("성장장애 의심", "체중이나 키가 잘 크지 못하거나 체중과 키가 동시에 잘 크지 않으면 성장장애, 만성질환, 양육 방식 문제 등의 가능성"),
]


def main():
    rows = []
    for k, c in GROWTH_RULE:
        rows.append(("성장 판단 원칙", k, c))
    for k, c in HEIGHT:
        rows.append(("키 성장속도", k, c))
    for k, c in WEIGHT:
        rows.append(("체중 증가", k, c))
    for k, c in HEAD:
        rows.append(("머리둘레", k, c))
    for k, c in SHORT_STATURE:
        rows.append(("저신장", k, c))

    with io.open(D("data", "kb", "kb_growth.csv"), "w", encoding="utf-8-sig", newline="") as fp:
        w = csv.writer(fp)
        w.writerow(["category", "key", "content"])
        w.writerows(rows)

    chunks = []
    for ln in io.open(D("data", "kb", "kb_chunks.jsonl"), encoding="utf-8"):
        c = json.loads(ln)
        if c["type"] != "growth":
            chunks.append(c)

    def add(cid, text, meta):
        chunks.append({"id": cid, "type": "growth", "text": text, "meta": meta, "source": SRC})

    for k, c in GROWTH_RULE:
        add("grow_rule_%s" % k, "[성장 판단 원칙 — %s] %s" % (k, c), {"kind": "rule"})
    for k, c in HEIGHT:
        add("grow_h_%s" % k, "정상 키 성장속도 — %s: %s" % (k, c), {"kind": "height", "age_label": k})
    for k, c in WEIGHT:
        add("grow_w_%s" % k, "정상 체중 증가 — %s: %s" % (k, c), {"kind": "weight", "age_label": k})
    for k, c in HEAD:
        add("grow_head_%s" % k, "머리둘레 — %s: %s" % (k, c), {"kind": "head_circumference"})
    for k, c in SHORT_STATURE:
        add("grow_short_%s" % k, "저신장 — %s: %s" % (k, c), {"kind": "short_stature"})

    with io.open(D("data", "kb", "kb_chunks.jsonl"), "w", encoding="utf-8") as fp:
        for c in chunks:
            fp.write(json.dumps(c, ensure_ascii=False) + "\n")

    print("성장 KB 추가 완료")
    for t, n in collections.Counter(c["type"] for c in chunks).most_common():
        print("  %-24s %4d" % (t, n))
    print("  %-24s %4d" % ("합계", len(chunks)))


if __name__ == "__main__":
    main()
