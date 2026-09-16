# -*- coding: utf-8 -*-
"""발달을 보는 기본 원칙 — "우리 아이 잘 자라고 있나요?" 에 답할 자료.

왜 필요한가
  월령별 이정표는 1,138조각이나 있는데, 정작 "그래서 우리 아이 괜찮은 건가요"
  같은 막연한 걱정에는 답할 게 없었다. 검색하면 "키 성장속도 0~6개월",
  "4세 제자리에서 뛸 수 없어요" 같은 무관한 조각만 올라와 tier 3 으로 빠졌다.
  부모가 제일 먼저 묻는 질문인데 빈칸이었다.

출처와 이용조건
  질병관리청 국가건강정보포털 「정상소아의 성장(발달)」
  https://health.kdca.go.kr/healthinfo/biz/health/gnrlzHealthInfo/gnrlzHealthInfo/gnrlzHealthInfoView.do?cntnts_sn=6485
  공공누리 제4유형 — 출처표시 + 상업적이용금지 + 변경금지.

  변경금지라서 **원문 문장을 그대로** 담는다. 우리 말로 고쳐 쓰면 2차적 저작물이 된다.
  앞에 짧은 머리말만 붙여 검색에 걸리게 하고, 인용 부분은 손대지 않는다.
  출처는 kb_source 에 남고 화면 근거 카드에 기관명·문서명으로 함께 나간다.

  ※ 상업적 이용은 이 조건 밖이다. 제품화한다면 질병관리청에 별도 문의가 필요하다.
    기존 국가건강정보포털 출처 303조각도 같은 조건이다.
"""
import collections
import csv
import io
import json
import os

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
D = lambda *p: os.path.join(BASE, *p)  # noqa: E731

SRC = "국가건강정보포털 정상소아의 성장(발달)"

# (id, 머리말, 원문 인용)
ITEMS = [
    ("개인차",
     "아이마다 발달 속도가 다른가요? 우리 아이가 아직 못 하는 게 있으면 문제인가요?",
     "아이마다 발달하는 속도와 양상이 서로 차이가 나기 때문에 특정 연령에 보일 수 있는 능력이 "
     "현재 아이에게 나타나지 않는다고 해서 모두 발달에 이상이 있다고 말할 수는 없습니다."),
    ("순서",
     "발달은 어떤 순서로 일어나나요?",
     "신체적인 발달은 정상적으로 머리 부분이 먼저 발달하고 이어서 다른 신체 부위의 발달이 일어납니다."),
    ("영역",
     "발달은 어떤 영역으로 나누어 보나요?",
     "보통 이 시기의 발달은 대근육 운동 발달, 소근육 운동 발달, 언어 발달, "
     "행동 및 사회성 발달, 감각(시각, 청각) 발달로 나누어 볼 수 있습니다."),
    ("상담시점",
     "언제 병원에 가봐야 하나요? 어느 정도면 걱정해야 하나요?",
     "다음과 같은 경우에는 의사와 의논할 필요가 있습니다. "
     "아이가 평상시와 다르게 보이거나 무언가 상태가 정상이 아닌 것 같거나 아무리 달래도 달래지 않는 경우, "
     "아이의 성장이나 발달이 정상이 아닌 것처럼 보일 때, 아이의 발달이 이정표를 따르지 못할 때."),
    ("퇴행",
     "되던 것을 못 하게 되면 어떻게 하나요?",
     "아이의 발달이 이정표를 따르지 못할 때. 예를 들면, 9개월 때에는 손을 잡아주면 서는 자세를 "
     "쉽게 취할 수 있었던 아이가 12개월 때에는 혼자 앉아있지 못하는 경우입니다."),
    ("돕는법",
     "집에서 아이 발달을 어떻게 도울 수 있나요?",
     "책을 보게 해 줌. 쇼핑센터, 동물원 등 다양한 경험을 하게해 줌. 공놀이를 함. "
     "주변의 물건이나 사람의 이름을 말해주고 책을 읽어주어 어휘력을 키워줌."),
    ("신체증상",
     "아이가 자꾸 어디가 아프다고 해요.",
     "목이 아프다, 배가 아프다는 등 자주 신체적인 증상을 호소하는 것은 "
     "단순히 아이가 자신의 신체에 대한 자각이 증가하기 때문일 수 있습니다."),
]


def main() -> None:
    with io.open(D("data", "kb", "kb_dev_basics.csv"), "w", encoding="utf-8-sig", newline="") as fp:
        w = csv.writer(fp)
        w.writerow(["key", "lead", "quote"])
        w.writerows(ITEMS)

    chunks = [c for c in (json.loads(l) for l in
                          io.open(D("data", "kb", "kb_chunks.jsonl"), encoding="utf-8"))
              if c["type"] != "dev_basics"]

    for key, lead, quote in ITEMS:
        chunks.append({
            "id": "devb_%s" % key,
            "type": "dev_basics",
            # 머리말은 검색에 걸리라고 우리가 붙인 것, 뒤는 원문 그대로다
            "text": "%s %s" % (lead, quote),
            "meta": {"kind": "principle", "verbatim": True},
            "source": SRC,
        })

    with io.open(D("data", "kb", "kb_chunks.jsonl"), "w", encoding="utf-8") as fp:
        for c in chunks:
            fp.write(json.dumps(c, ensure_ascii=False) + "\n")

    print("발달 기본 원칙 추가 완료")
    for t, n in collections.Counter(c["type"] for c in chunks).most_common(6):
        print("  %-24s %4d" % (t, n))
    print("  %-24s %4d" % ("합계", len(chunks)))


if __name__ == "__main__":
    main()
