# -*- coding: utf-8 -*-
"""RAG 지식베이스 빌드
  kb_kdst.csv      K-DST 736문항 (질병관리청·보건복지부)
  kb_mapping.csv   K-DST 영역 → 발달재활 법정 치료영역 매핑
  kb_policy.csv    발달재활서비스 바우처 제도 (복지로·보건복지부)
  kb_chunks.jsonl  임베딩용 청크 (출처 메타 포함)
"""
import csv, io, os, json, collections

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
D = lambda *p: os.path.join(BASE, *p)

# ── 1) K-DST
kdst = list(csv.DictReader(io.open(D("data", "kdst_items.csv"), encoding="utf-8-sig")))

# ── 2) 매핑 테이블: K-DST 6영역 → broso 법정 치료영역 10종
#    ※ 초안. 전문가 자문으로 검증 후 확정해야 함 (verified 컬럼)
MAPPING = [
    ("언어",     "언어재활",     1, "표현·수용언어 지연, 조음 문제", "no"),
    ("언어",     "청능재활",     2, "언어지연 시 청각 문제 배제 필요", "no"),
    ("인지",     "언어재활",     2, "인지-언어는 상호 영향", "no"),
    ("인지",     "놀이심리재활", 2, "놀이를 매개로 한 인지 개입", "no"),
    ("사회성",   "놀이심리재활", 1, "또래관계·상호작용 어려움", "no"),
    ("사회성",   "미술심리재활", 2, "비언어적 정서표현 경로", "no"),
    ("사회성",   "음악재활",     2, "집단 음악활동을 통한 상호작용", "no"),
    ("대근육운동", "운동발달재활", 1, "전신 협응·균형", "no"),
    ("대근육운동", "심리운동",     2, "움직임 기반 발달 촉진", "no"),
    ("소근육운동", "감각발달재활", 1, "손 기능·감각통합", "no"),
    ("소근육운동", "운동발달재활", 2, "미세운동 협응", "no"),
    ("자조",     "행동발달재활", 1, "일상생활 기술·행동 형성", "no"),
    ("자조",     "감각발달재활", 2, "감각 예민이 자조 수행을 방해", "no"),
]
with io.open(D("data", "kb", "kb_mapping.csv"), "w", encoding="utf-8-sig", newline="") as fp:
    w = csv.writer(fp)
    w.writerow(["kdst_domain", "therapy_area", "priority", "rationale", "expert_verified"])
    w.writerows(MAPPING)

# ── 3) 제도 정보
POLICY = [
    ("지원대상", "만 18세 미만 등록장애인(뇌병변·지적·자폐성·시각·청각·언어). 장애 미등록이라도 해당 장애가 예견되는 9세 미만 아동은 전문의가 작성한 발달재활서비스 의뢰서와 세부영역검사결과서로 신청 가능", "복지로"),
    ("소득기준", "기준 중위소득 180% 이하, 가구별 차등 지원", "복지로"),
    ("지원금액", "기초생활수급 월 26만원 / 차상위 24만원 / 중위 65% 이하 22만원 / 120% 이하 20만원 / 180% 이하 18만원", "복지로"),
    ("본인부담금", "소득 등급별 0원 ~ 8만원", "복지로"),
    ("신청처", "주민등록 주소지 읍·면·동 행정복지센터(주민센터)", "복지로"),
    ("서비스영역", "언어·청능, 미술심리, 음악, 놀이심리, 행동발달, 재활심리, 심리운동, 감각발달, 운동발달 재활", "보건복지부"),
    ("기준단가", "월 8회(주 2회), 회당 30,000원 기준. 시·군·구가 지역 시장가격·제공인력 자격 등을 고려해 적정단가 설정 가능", "보건복지부"),
    ("가격공시", "제공기관별 서비스 단가는 시·도 및 시·군·구, 중앙장애아동·발달장애인지원센터(broso.or.kr), 사회서비스 전자바우처에서 확인", "보건복지부"),
    ("발달지연 정의", "해당 연령에 이루어져야 할 발달이 성취되지 않은 상태. 발달선별검사에서 해당 연령 정상 기대치보다 25% 뒤쳐진 경우", "국가건강정보포털"),
    ("언어발달 경고신호", "18개월에 말보다 몸짓으로 의사표현 / 만 2세에 두 단어 문장을 만들지 못함 / 만 3세에 의사표시 문장을 못함 → 언어발달 이상 의심", "국가건강정보포털"),
    ("표현어휘 이정표", "18개월 50~100개 낱말, 18개월~2세 평균 100~200개 낱말", "국가건강정보포털"),
]
with io.open(D("data", "kb", "kb_policy.csv"), "w", encoding="utf-8-sig", newline="") as fp:
    w = csv.writer(fp); w.writerow(["topic", "content", "source"]); w.writerows(POLICY)

# ── 4) 임베딩용 청크
chunks = []
for r in kdst:
    chunks.append({
        "id": "kdst_%s_%s_%s" % (r["age_lo"], r["domain"], r["no"]),
        "type": "developmental_milestone",
        "text": "%s 아동의 %s 발달 기준: %s" % (r["age_label"], r["domain"], r["question"]),
        "meta": {"age_lo": int(r["age_lo"]), "age_hi": int(r["age_hi"]),
                 "domain": r["domain"], "item_no": int(r["no"])},
        "source": "질병관리청·보건복지부 한국 영유아 발달선별검사(K-DST) 개정판",
    })
for dom, area, pri, why, ver in MAPPING:
    chunks.append({
        "id": "map_%s_%s" % (dom, area),
        "type": "therapy_mapping",
        "text": "K-DST '%s' 영역에서 어려움이 관찰되면 '%s' 치료를 %d순위로 고려한다. 근거: %s" % (dom, area, pri, why),
        "meta": {"kdst_domain": dom, "therapy_area": area, "priority": pri, "expert_verified": ver},
        "source": "자체 매핑 초안 (전문가 자문 검증 필요)",
    })
for topic, content, src in POLICY:
    chunks.append({
        "id": "policy_%s" % topic,
        "type": "policy",
        "text": "[%s] %s" % (topic, content),
        "meta": {"topic": topic},
        "source": src,
    })

with io.open(D("data", "kb", "kb_chunks.jsonl"), "w", encoding="utf-8") as fp:
    for c in chunks:
        fp.write(json.dumps(c, ensure_ascii=False) + "\n")

import shutil
shutil.copy(D("data", "kdst_items.csv"), D("data", "kb", "kb_kdst.csv"))

print("지식베이스 빌드 완료 → data/kb/")
print("  kb_kdst.csv     %4d문항" % len(kdst))
print("  kb_mapping.csv  %4d개 매핑 (전문가 검증 대기)" % len(MAPPING))
print("  kb_policy.csv   %4d개 제도 항목" % len(POLICY))
print("  kb_chunks.jsonl %4d청크" % len(chunks))
print()
for t, c in collections.Counter(c["type"] for c in chunks).most_common():
    print("    %-24s %d" % (t, c))
