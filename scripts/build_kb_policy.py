# -*- coding: utf-8 -*-
"""제도·치료영역 지식베이스 (사회서비스 전자바우처 공식 문서 기반)"""
import csv, io, os, json
BASE=os.path.join(os.path.dirname(os.path.abspath(__file__)),"..")
D=lambda *p: os.path.join(BASE,*p)
SS="사회서비스 전자바우처 (보건복지부)"

POLICY=[
 ("사업목적","성장기 장애아동에게 의사소통, 운동, 감각 등의 기능향상과 행동발달을 위한 발달재활서비스 지원",SS),
 ("대상연령","18세 미만. 연령은 신청일 기준으로 판정하되, 지원기간은 대상자로 선정된 장애아동이 18세가 되는 달까지",SS),
 ("대상 장애유형","뇌병변, 지적, 자폐성, 청각, 언어, 시각 장애 아동. 장애인복지법상 등록장애아동에 한하며, 9세 미만 영유아는 발달재활서비스 의뢰서 및 검사자료로 대체 가능. 장애등록이 안 된 대상자가 만 9세 도래 시에는 9세가 되는 달까지만 지원",SS),
 ("소득기준","기준중위소득 180% 이하. 단 180%를 초과해도 장애아동 2명 이상 가구이거나 부모 중 1명 이상이 중증장애인인 가정은 시·군·구청장이 인정하는 경우 예산범위 내에서 마형(본인부담금 8만원) 지원 가능",SS),
 ("자격 재판정","기존 이용자는 매년 반기별(연 2회) 소득기준 조사 후 적합한 경우 계속 이용 가능",SS),
 ("서비스 내용","언어·청능(聽能), 미술·음악, 행동·놀이·심리, 감각·운동 등 발달재활 서비스 제공. 장애아동 및 부모의 수요에 따라 사업실시 기관이 다양한 서비스 개발 가능",SS),
 ("기준단가","월 8회(주 2회), 회당 32,500원 기준. 시·군·구에서 제공기관 지정 시 해당지역 시장가격, 전년도 바우처가격, 타지역가격, 제공인력의 자격 및 경력 등을 고려하여 적정단가 설정 가능",SS),
 ("지원금액 다형","기초생활수급자(다형): 바우처 월 26만원, 본인부담금 면제",SS),
 ("지원금액 가형","차상위계층(가형): 바우처 월 24만원, 본인부담금 2만원",SS),
 ("지원금액 나형","차상위 초과~기준중위소득 65% 이하(나형): 바우처 월 22만원, 본인부담금 4만원",SS),
 ("지원금액 라형","중위소득 65% 초과~120% 이하(라형): 바우처 월 20만원, 본인부담금 6만원",SS),
 ("지원금액 마형","중위소득 120% 초과~180% 이하(마형): 바우처 월 18만원, 본인부담금 8만원",SS),
 ("본인부담금 납부","서비스 대상자가 제공기관에 직접 사전 납부. 계좌입금 원칙이며 현금 납부 시 영수증 관리 필요. 본인부담금을 납부하지 않고 바우처로 결제하면 부당거래로 간주",SS),
 ("신청권자","본인, 부모 또는 가구원, 대리인, 복지담당공무원이 직권으로 신청 가능",SS),
 ("신청 장소","서비스 대상자의 주민등록상 주소지 읍·면·동 주민센터. 온라인 신청은 복지로(bokjiro.go.kr)",SS),
 ("신청 시기","연중 신청 가능. 단 매월 27일 18:00까지 시·군·구에서 한국사회보장정보원으로 대상자 선정 결과가 전송된 경우에 한해 익월 바우처 생성",SS),
 ("가격공시 확인처","제공기관별 서비스 단가는 시·도 및 시·군·구, 중앙장애아동·발달장애인지원센터(broso.or.kr), 사회서비스 전자바우처(socialservice.or.kr)에서 확인 가능",SS),
 ("발달지연 정의","해당 연령에 이루어져야 할 발달이 성취되지 않은 상태. 발달선별검사에서 해당 연령 정상 기대치보다 25% 뒤쳐진 경우","국가건강정보포털"),
 ("언어발달 경고신호","18개월에 말보다 몸짓으로 의사표현 / 만 2세에 두 단어 문장을 만들지 못함 / 만 3세에 의사표시 문장을 못함 → 언어발달 이상 의심","국가건강정보포털"),
 ("표현어휘 이정표","18개월 50~100개 낱말, 18개월~2세 평균 100~200개 낱말","국가건강정보포털"),
]

# 부모가 "이게 뭐예요?"라고 물을 법정 치료영역 10종 설명
AREAS=[
 ("언어재활","말이 늦거나 발음이 부정확하거나 의사소통이 어려운 아동의 언어 능력을 키우는 치료입니다. 표현언어(말하기)와 수용언어(알아듣기)를 함께 다룹니다.","언어·청능"),
 ("청능재활","소리를 듣고 구별하고 이해하는 능력을 훈련합니다. 언어가 늦을 때 청각 문제가 원인일 수 있어 함께 확인하는 경우가 많습니다.","언어·청능"),
 ("미술심리재활","그림과 만들기를 매개로 감정을 표현하게 돕습니다. 말로 표현하기 어려워하는 아동에게 적합합니다.","미술·음악"),
 ("음악재활","악기 연주와 노래, 리듬 활동으로 정서 조절과 상호작용을 돕습니다. 집단으로 진행하면 사회성 훈련도 됩니다.","미술·음악"),
 ("놀이심리재활","놀이를 매개로 정서·행동 문제를 다룹니다. 또래관계가 어렵거나 불안이 높은 아동에게 많이 권합니다.","행동·놀이·심리"),
 ("행동발달재활","반복 행동이나 자해, 공격성 등 특정 행동을 줄이고 필요한 행동을 익히도록 돕습니다.","행동·놀이·심리"),
 ("재활심리","심리 평가와 상담을 통해 정서적 어려움을 다룹니다.","행동·놀이·심리"),
 ("감각발달재활","촉각·청각·전정 감각 등이 지나치게 예민하거나 둔감한 경우 감각을 조절하고 통합하도록 돕습니다. 소리에 예민하거나 특정 촉감을 거부하는 아동에게 권합니다.","감각·운동"),
 ("운동발달재활","앉기·걷기·뛰기 같은 대근육과 손 사용 같은 소근육 기능을 향상시킵니다.","감각·운동"),
 ("심리운동","움직임 활동을 통해 신체·정서·인지 발달을 함께 촉진합니다.","감각·운동"),
]

with io.open(D("data","kb","kb_policy.csv"),"w",encoding="utf-8-sig",newline="") as fp:
    w=csv.writer(fp); w.writerow(["topic","content","source"]); w.writerows(POLICY)
with io.open(D("data","kb","kb_therapy_areas.csv"),"w",encoding="utf-8-sig",newline="") as fp:
    w=csv.writer(fp); w.writerow(["therapy_area","description","official_group"]); w.writerows(AREAS)

# 청크 재생성
kdst=list(csv.DictReader(io.open(D("data","kdst_items.csv"),encoding="utf-8-sig")))
mapping=list(csv.reader(io.open(D("data","kb","kb_mapping.csv"),encoding="utf-8-sig")))[1:]
chunks=[]
for r in kdst:
    chunks.append({"id":"kdst_%s_%s_%s"%(r["age_lo"],r["domain"],r["no"]),"type":"developmental_milestone",
        "text":"%s 아동의 %s 발달 기준: %s"%(r["age_label"],r["domain"],r["question"]),
        "meta":{"age_lo":int(r["age_lo"]),"age_hi":int(r["age_hi"]),"domain":r["domain"],"item_no":int(r["no"])},
        "source":"질병관리청·보건복지부 한국 영유아 발달선별검사(K-DST) 개정판"})
for dom,area,pri,why,ver in mapping:
    chunks.append({"id":"map_%s_%s"%(dom,area),"type":"therapy_mapping",
        "text":"K-DST '%s' 영역에서 어려움이 관찰되면 '%s' 치료를 %s순위로 고려한다. 근거: %s"%(dom,area,pri,why),
        "meta":{"kdst_domain":dom,"therapy_area":area,"priority":int(pri),"expert_verified":ver},
        "source":"자체 매핑 초안 (전문가 자문 검증 필요)"})
for t,c,s in POLICY:
    chunks.append({"id":"policy_%s"%t.replace(" ","_"),"type":"policy","text":"[%s] %s"%(t,c),
                   "meta":{"topic":t},"source":s})
for a,d,g in AREAS:
    chunks.append({"id":"area_%s"%a,"type":"therapy_area",
        "text":"%s란? %s (공식 분류: %s)"%(a,d,g),
        "meta":{"therapy_area":a,"official_group":g},"source":SS})

with io.open(D("data","kb","kb_chunks.jsonl"),"w",encoding="utf-8") as fp:
    for c in chunks: fp.write(json.dumps(c,ensure_ascii=False)+"\n")

import collections
print("지식베이스 갱신 완료")
for t,c in collections.Counter(c["type"] for c in chunks).most_common():
    print("  %-24s %4d"%(t,c))
print("  %-24s %4d"%("합계",len(chunks)))
