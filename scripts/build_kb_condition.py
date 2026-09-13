# -*- coding: utf-8 -*-
"""질환·발달 지식 KB (국가건강정보포털 '언어장애 - 아동 언어장애의 진단과 치료')
출처: 질병관리청 국가건강정보포털 cntnts_sn=6188
※ 성인(실어증·말실행증) 내용은 서비스 대상 외로 제외
"""
import csv, io, os, json, collections
BASE=os.path.join(os.path.dirname(os.path.abspath(__file__)),"..")
D=lambda *p: os.path.join(BASE,*p)
SRC="질병관리청 국가건강정보포털 — 아동 언어장애의 진단과 치료"

# 1) 연령별 정상 언어발달 이정표 (정량)
MILESTONE=[
 ("10~12개월","첫 낱말을 말하기 시작함. 20여개의 낱말을 이해함 (엄마, 아빠, 아가, 야옹이, 물, 우유, 까꿍 등)"),
 ("18개월","50개에서 100개 정도의 낱말이나 어구를 표현할 수 있음"),
 ("18개월~2세","평균 100개에서 200개의 낱말을 말함. 두 낱말을 조합해 사용함 (엄마 우유, 이거 까까 등)"),
 ("3세","주어+목적어+서술어 등 3가지 구문 구조를 사용함 (엄마 빵 먹어, 던져서 공 받구 등)"),
]

# 2) 언어발달 지연 의심 징후 — 경고신호 (우리 KB의 핵심 공백이었음)
REDFLAG=[
 ("3개월","소리나는 쪽을 바라보지 않고, 울 때 외에 소리를 거의 내지 않음"),
 ("6개월","부모를 보며 눈 맞추고 웃지 않거나 옹알이를 하지 않음"),
 ("12개월","옹알이를 하지 않고, '안 돼'라고 말해도 하던 활동을 중단하지 않음"),
 ("24개월","의미 있는 단어를 말하지 않고 자기 이름을 언급하지 못함. 간단한 지시를 따르지 못함"),
 ("36개월","본인의 이름을 말하지 않음. '무엇'과 '어디'에 대한 질문을 이해하지 못함. 묻는 질문을 반복하여 답변함. 다른 사람들의 말을 메아리처럼 되풀이함"),
]

# 3) 아동 언어장애 유형
TYPES=[
 ("언어발달장애","수용언어는 괜찮으나 표현언어만 지연되는 경우와, 수용·표현 모두 지연된 경우로 구분. 지능·청력·인지·신경학적 손상이 원인인 경우가 많으며, 기저 질환이나 문제가 없으면 '단순언어장애'라고 함. 지적장애, 전반적 발달장애, 청각장애, 학습장애, 정서장애, 뇌기능장애, 자폐 등 기질적 원인으로도 지연될 수 있음","언어재활"),
 ("조음발달장애","혀·입술·치아·입천장 등으로 말소리를 만드는 과정에 이상이 생겨 발음이 제대로 되지 않는 경우. 구어가 불명료해 의사소통이 어려움. 순수 조음장애 외에 지적장애, 구개파열, 뇌성마비, 청각장애가 동반될 때도 흔함","언어재활"),
 ("유창성장애","말이 비정상적으로 자주 끊기거나 속도가 불규칙하거나 말할 때 불필요한 노력이 들어감. 소리·음절 반복, 말소리 연장, 말 막힘이 나타남. 2~7세 발병이 가장 많고 98%가 10세 이전 발병","언어재활"),
]

# 4) 조음 오류 유형
ARTIC=[
 ("생략","음소를 빠뜨리고 발음하지 않는 오류로 종성에 흔히 나타남 (연필 → 연피)"),
 ("대치","목표 음소 대신 다른 음소로 바꾸어 발음하는 오류로 가장 흔함. 어려운 음소 대신 낼 수 있는 음소로 바꿈 (ㅅ → ㄷ)"),
 ("왜곡","변이음 형태로 바꾸어 발음. 목표 음소에 소음이 첨가되거나 조음기관을 잘못 사용"),
 ("첨가","목표 음소나 단어에 필요 없는 음소를 첨가하는 오류"),
]

# 5) 검사도구 — Core 2(진단지 분석)에서 인식해야 할 대상
TESTS=[
 ("SELSI","영유아 언어발달 선별검사","언어"),
 ("PRES","취학 전 아동의 수용언어 및 표현언어 발달척도. 19~78개월 아동 대상","언어"),
 ("그림어휘력검사","어휘 이해 능력 평가","언어"),
 ("언어문제 해결검사","주로 학령기 아동 대상","언어"),
 ("구문의미 이해력 검사","만 4세~초등 3학년 아동 대상","언어"),
 ("U-TAP","우리말 조음-음운평가. 자음정확도와 명료도 평가","조음"),
 ("덴버 영유아 발달선별검사","전반적 발달 선별","발달"),
 ("베일리 아동발달검사","전반적 발달 평가","발달"),
 ("사회성숙도검사","사회적 적응 능력 평가","발달"),
 ("웩슬러 지능검사","지능 평가","인지"),
]

# 6) 치료·예후·의뢰
CLINICAL=[
 ("치료 시기","언어치료는 어휘력이나 이해 능력이 폭발적으로 증가하는 시기인 3세를 넘지 않는 것이 좋음. 최근에는 조기진단·조기치료를 원칙으로 진단 즉시 치료할 것을 권장"),
 ("부모 역할","아동의 언어 발달에는 부모의 역할이 매우 중요. 부모 교육 후 가정에서도 각 아동의 수준에 맞는 치료를 병행해야 함"),
 ("동반장애 시","언어장애 외에 지적장애, 자폐, 청각장애, 뇌성마비 등 동반 장애가 있으면 각 질환에 따른 다각적·통합적 접근이 필요"),
 ("예후 - 지속률","만 3세경 단순언어장애로 진단될 경우 약 30%는 8세 이후까지 언어지연이 지속. 만 4세경 진단된 경우 약 40%에서 지속"),
 ("예후 - 학습","언어장애가 학령기를 지나서도 계속되면 학습장애로 이어지기 쉬움. 언어장애 아동의 약 절반이 학습능력 저하로 보고됨"),
 ("동반 행동문제","의사소통에 문제가 있는 아동은 추적관찰 시 과잉행동, 주의력 결핍, 불안장애 등 행동문제를 나타낼 수 있어 주의 필요"),
 ("의뢰 - 청각","소리나는 쪽을 바라보지 않을 경우 청각 문제 확인을 위해 이비인후과, 소아청소년과 진료 필요"),
 ("의뢰 - 언어평가","언어발달지연이 의심되면 체계적인 언어발달 평가 및 진단을 위해 재활의학과, 소아청소년과 진료 후 치료계획 수립"),
]

rows=[]
for age,c in MILESTONE: rows.append(("언어발달 이정표",age,c))
for age,c in REDFLAG:   rows.append(("언어발달 경고신호",age,c))
for n,c,a in TYPES:     rows.append(("아동 언어장애 유형",n,c))
for n,c in ARTIC:       rows.append(("조음 오류 유형",n,c))
for n,c,d in TESTS:     rows.append(("검사도구",n,"%s (영역: %s)"%(c,d)))
for n,c in CLINICAL:    rows.append(("치료·예후",n,c))
with io.open(D("data","kb","kb_conditions.csv"),"w",encoding="utf-8-sig",newline="") as fp:
    w=csv.writer(fp); w.writerow(["category","key","content"]); w.writerows(rows)

# 청크 추가 생성
chunks=[]
for ln in io.open(D("data","kb","kb_chunks.jsonl"),encoding="utf-8"):
    c=json.loads(ln)
    if c["type"] not in ("condition","red_flag","milestone_lang","assessment_tool","clinical"):
        chunks.append(c)
for age,c in MILESTONE:
    chunks.append({"id":"langms_%s"%age,"type":"milestone_lang",
        "text":"정상 언어발달 이정표 — %s: %s"%(age,c),
        "meta":{"age_label":age},"source":SRC})
for age,c in REDFLAG:
    chunks.append({"id":"redflag_%s"%age,"type":"red_flag",
        "text":"언어발달 지연을 의심할 수 있는 징후 — %s: %s"%(age,c),
        "meta":{"age_label":age,"severity":"warning"},"source":SRC})
for n,c,a in TYPES:
    chunks.append({"id":"cond_%s"%n,"type":"condition",
        "text":"%s: %s"%(n,c),"meta":{"condition":n,"therapy_area":a},"source":SRC})
for n,c in ARTIC:
    chunks.append({"id":"artic_%s"%n,"type":"condition",
        "text":"조음 오류 유형 '%s': %s"%(n,c),"meta":{"condition":"조음발달장애"},"source":SRC})
for n,c,d in TESTS:
    chunks.append({"id":"test_%s"%n,"type":"assessment_tool",
        "text":"검사도구 %s — %s (평가영역: %s)"%(n,c,d),
        "meta":{"tool":n,"domain":d},"source":SRC})
for n,c in CLINICAL:
    chunks.append({"id":"clin_%s"%n.replace(" ","_"),"type":"clinical",
        "text":"[%s] %s"%(n,c),"meta":{"topic":n},"source":SRC})

with io.open(D("data","kb","kb_chunks.jsonl"),"w",encoding="utf-8") as fp:
    for c in chunks: fp.write(json.dumps(c,ensure_ascii=False)+"\n")

print("질환 KB 추가 완료")
for t,c in collections.Counter(c["type"] for c in chunks).most_common():
    print("  %-24s %4d"%(t,c))
print("  %-24s %4d"%("합계",len(chunks)))
