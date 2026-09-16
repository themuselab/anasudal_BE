# 안아수달 — 백엔드

아이 발달이 걱정될 때, **검증된 공공 자료로만** 확인해볼 영역을 찾아주고 가까운 발달재활 기관을 추천하는 서비스.
이 저장소는 API·데이터·인프라이고, 화면은 [anasudal_FE](https://github.com/themuselab/anasudal_FE) 에 있습니다.

FastAPI · PostgreSQL 16 + pgvector · Redis · Gemini · AWS(ECS/ECR + SSM 게이트웨이)

---

## 무엇을 하는가

부모가 "30개월인데 두 단어 문장을 못 만들어요" 라고 쓰면,

1. **근거 검색** — 1,473개 지식 조각에서 월령에 맞는 3건을 벡터 검색으로 찾고
2. **답변 생성** — 그 근거 안에서만 Gemini 가 답을 쓰고(근거 밖이면 답하지 않음), 확인해볼 치료영역을 뽑고
3. **기관 추천** — 전국 2,866곳 중 그 영역을 다루는 곳을 지역 기준으로 3곳 고릅니다.

지켜야 할 선:

- **진단하지 않습니다.** "○○ 의심" 같은 표현을 쓰지 않고 "확인해볼 영역"으로만 안내합니다. 진단을 요구하는 질문은 검색·생성 전에 규칙으로 막습니다.
- **로그인이 없고 대화 원문을 저장하지 않습니다.** 답변 테이블에는 치료영역 코드·키워드와, 응답 뒤 따로 만든 40자 요약만 남습니다.
- 근거가 없으면 지어내지 않고 범위 밖임을 알립니다.

---

## 빠른 시작

```bash
# 1) DB + Redis
cd backend && docker compose up -d          # pgvector/pgvector:pg16 · redis:7 · 스키마 자동 실행

# 2) 데이터 적재 (data/ 는 이 저장소에 없습니다 — 아래 "데이터" 참고)
cd .. && python scripts/kb_to_csv.py        # data/kb/*.jsonl → data/kb_chunks.csv
psql "postgresql://anasudal:anasudal@localhost:5432/anasudal" -v csv_dir="$PWD/data" -f db/02_load.sql

# 3) API
cd backend
cp .env.example .env                        # GEMINI_API_KEYS · GEMINI_SUMMARY_KEY 채우기
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000   # http://localhost:8000/docs
```

`backend/api.http` 를 VS Code REST Client 로 열면 화면 흐름 순서대로 눌러볼 수 있습니다.
`python scripts/smoke_api.py` 는 같은 흐름을 한 번에 돌립니다.

---

## API

모든 응답이 같은 봉투를 씁니다 (`/health` 제외). OpenAPI 문서의 스키마는 `data` 부분입니다.

```
성공  { "success": true,  "data": { ... } }
실패  { "success": false, "error": { "code": "SESSION_NOT_FOUND", "message": "...", "details": null } }
```

| 화면 | 엔드포인트 |
|---|---|
| 첫 화면 칩 | `GET /v1/chat/prompts` — `{prompt_id, text, emoji}` 3개, 호출마다 회전 |
| 세션 | `POST /v1/sessions` · `GET|PATCH /v1/sessions/{id}` |
| 질문 → 답변 | `POST /v1/chat/ask` · **`POST /v1/chat/ask/stream` (SSE, 프론트 기본)** |
| 근거 보기 | `GET /v1/chat/answers/{id}/evidence` |
| 기관 추천 | `POST /v1/chat/recommend` |
| 둘러보기 | `GET /v1/institutions?region_id&q&sort&page&size` |
| 기관 상세 | `GET /v1/institutions/{사업자번호}` |
| 지역 | `GET /v1/regions/sido` · `GET /v1/regions?sido=` |
| 피드백 | `GET /v1/feedback/reasons` · `POST /v1/feedback` |

### SSE 스트리밍

```
event: meta   data: {"evidence_count": 3}      ← 검색 끝, 생성 시작
event: delta  data: {"text": "삼성복지재단…"}   ← 본문 조각 (여러 번)
event: done   data: {AskResponse}              ← 최종본. 볼드·마무리 문장 반영 → 이걸로 교체
event: error  data: {"code": "...", "message": "..."}
```

`GEMINI_THINKING_LEVEL=low` 로 첫 글자 1.7초 / 전체 2.8초입니다 (기본 thinking 은 7.5초 / 9초였습니다).

### 오류 코드

| HTTP | code | 언제 |
|---|---|---|
| 400 | `VALIDATION_ERROR` | 필드 누락·형식 오류 (`details[].field`) |
| 400 | `FEEDBACK_REASON_REQUIRED` · `INVALID_REASON_CODE` · `MESSAGE_EMPTY` | 입력 사유별 구분 |
| 404 | `SESSION_NOT_FOUND` · `ANSWER_NOT_FOUND` · `REGION_NOT_FOUND` · `INSTITUTION_NOT_FOUND` · `CHUNK_NOT_FOUND` · `NOT_FOUND` | |
| 409 | `ANSWER_NOT_GROUNDED` · `ANSWER_SESSION_MISMATCH` | 근거 없는 답변으로 추천 요청 등 |
| 429 | `RATE_LIMITED` | IP 당 시간당 질문 상한 |
| 503 | `LLM_RATE_LIMITED` | Gemini 키가 모두 한도에 걸림 (`details.retry_after_sec`). 아래 "키 운영" 참고 |
| 502 / 500 | `LLM_FAILED` / `INTERNAL_ERROR` | |

---

## 데이터

### 기관 2,866곳

| 항목 | 채움 | 출처 |
|---|---|---|
| 이름·사업자번호·치료영역·회기당 단가 | 100% | **broso.or.kr 2026 시·도별 발달재활서비스 가격 공시** (17개 시·도 xlsx) |
| 주소 | 93.1% | 보건복지부 공공데이터 + 사회보장정보원 API |
| 전화 | 89.4% | 〃 |
| 좌표 | 65.6% | 지오코딩 |
| 자체 홈페이지 | 35.6% | 카카오 로컬 API (주소 1차 · 지역번호 2차 검증) |
| 운영시간·대기·중증도 | 0% | 공개 출처 없음 — 전화조사나 기관 입력이 필요 |

치료영역은 **법정 10종**이 한계입니다. 인지치료·사회성그룹 같은 세부 분야는 어느 공공 출처에도 없습니다.

### 지식베이스 1,496조각

K-DST(영유아 발달선별검사), 새싹과단비 발달길잡이, 국가건강정보포털(언어장애·자폐스펙트럼·뇌성마비·다운증후군·
난청·굴절이상·지적발달장애·틱장애·정상 성장), 발달재활서비스 바우처 제도에서 정리했습니다. 768차원 임베딩
(`gemini-embedding-2`)과 함께 `kb_chunk` 테이블에 들어갑니다.

> **이 저장소에 `data/` 는 포함하지 않았습니다.** 지식베이스는 국가건강정보포털·새싹과단비 등의 내용을 정리한
> 2차 저작물이라 공개 재배포 조건을 확인하기 전까지 비공개로 둡니다. 아래 스크립트로 다시 만들 수 있고,
> 팀 내부에서는 별도로 공유합니다.

### 데이터 파이프라인 (`scripts/`)

| 스크립트 | 하는 일 |
|---|---|
| `fetch_broso_all.py` | 가격 공시 17개 시·도 xlsx 수집 → 치료영역·단가 |
| `fetch_ssis_chunk.py` · `merge_ssis.py` | 사회보장정보원 API (15만 건 중 장애아동가족지원 추출) |
| `parse_nise.py` · `parse_seouli.py` · `supplement_local.py` | NISE 온맘·서울시·지자체 공공데이터 |
| `geocode_nominatim.py` · `geocode_retry.py` | 주소 → 좌표 |
| `enrich_kakao.py` | 카카오 로컬 API 로 홈페이지·전화 보강 (주소·지역번호 교차검증) |
| `build_nationwide.py` · `build_master.py` | 전국 마스터 CSV 생성 |
| `parse_kdst.py` · `parse_ksied.py` · `build_kb_*.py` | 지식베이스 조각 만들기 |
| `embed_gemini.py` · `kb_to_csv.py` | 임베딩 생성 → 적재용 CSV |
| `eval_retrieval.py` · `eval_embedding.py` | 검색 품질 측정 |
| `smoke_api.py` | 배포 후 화면 흐름 점검 |

키는 전부 환경 변수로 받습니다 (`KAKAO_KEY`, `GEMINI_API_KEY`, `DATA_GO_KR_KEY`).

---

## 설계 문서

| 문서 | 내용 |
|---|---|
| [backend/docs/architecture.md](backend/docs/architecture.md) | 인프라 → 데이터 → 질문이 답이 되기까지 → 👍👎 가 쌓이는 곳 |
| [backend/docs/rag-tuning.md](backend/docs/rag-tuning.md) | top_k·연령 필터·임계값을 어떻게 정했나, 회귀 검사, 답변 세 단 |

## RAG 설계 근거

30개 평가 질문(난이도 0~3)으로 측정해 정한 값입니다.

| 항목 | 결정 | 근거 |
|---|---|---|
| 검색 방식 | Gemini 임베딩 벡터 검색 | 적중 96.3% / 정밀 80.2% (BM25 는 77.8% / 63.0%) |
| top_k | **3** | 3에서 정밀도가 가장 높았고, 더 늘리면 무관한 근거가 섞임 |
| 유사도 임계값 | **쓰지 않음** | 범위 밖 질문도 0.73~0.77 로 나와 임계값으로는 못 거름 |
| 범위 밖 판별 | 모델이 `grounded` 플래그로 | 위 이유로 점수 기반 폴백 대신 |
| 진단 요구 차단 | 검색 전 규칙(정규식) | 유사도로는 안 걸러짐 |
| 연령 필터 | 월령으로 조각 제한 | 적중 +3.7%p |

---

## 구조

```
backend/          FastAPI — 도메인별 분리 (region · institution · knowledge · chat · feedback)
  app/core/       설정 · DB 풀 · Redis · Gemini · 오류/응답 봉투
  api.http        화면 흐름 순서대로 눌러보는 요청 모음
db/
  01_schema.sql   테이블 · 머티리얼라이즈드 뷰 4개 · 함수 · 시드
  02_load.sql     CSV → 스테이징 → 본 테이블
  03~05_*.sql     이미 만든 DB 용 마이그레이션
infra/terraform/  VPC · RDS · ElastiCache · ECR · ECS(Fargate) · SSM 게이트웨이 EC2 · GitHub OIDC
infra/scripts/    첫 이미지 푸시 · SSM 포트포워딩 · DB 초기화 · 게이트웨이 셸
scripts/          데이터 파이프라인 · 평가 · 스모크 테스트
.github/workflows/deploy.yml   main push → ECR → ECS 롤링 배포
```

### 주요 테이블

`institution` (사업자번호 PK) · `institution_area_price` (기관×영역×방식×연도) · `therapy_area` (법정 10종 + 기타) ·
`region` · `kb_chunk` (768차원 벡터, HNSW 코사인 인덱스) · `kb_source` · `area_mapping` (K-DST 영역 → 치료영역) ·
`session` (24시간 후 만료) · `answer` (**원문 없음**) · `answer_evidence` · `answer_recommendation` ·
`feedback` · `training_sample` (👍👎 눌린 답변만 학습용으로).

머티리얼라이즈드 뷰: `mv_institution_card`(카드 한 줄) · `mv_kb_evidence` · `mv_area_coverage` · `mv_feedback_summary`.
`SELECT refresh_all_mvs();` 로 갱신합니다.

---

## Gemini 키 운영 — 429 를 맞으면

키를 두 묶음으로 나눠 씁니다.

| 묶음 | 환경 변수 | 쓰는 곳 |
|---|---|---|
| 답변·임베딩 | `GEMINI_API_KEYS` (콤마로 여러 개) | 사용자가 기다리는 경로 — 질문 임베딩과 답변 생성 |
| 요약 | `GEMINI_SUMMARY_KEY` | 응답을 보낸 뒤 백그라운드로 질문을 한 문장으로 줄여 DB 에 넣는 일 |

요약을 분리한 이유는 두 가지입니다. 답변 속도에 영향을 주지 않고, 요약이 답변 쿼터를 갉아먹지 않습니다.
요약이 실패해도 사용자에게는 아무 일도 일어나지 않습니다 — `answer.question_summary` 가 비어 있을 뿐입니다.

### 한도에 걸리면 네 단계로 물러납니다

1. **다른 키로 즉시 교체.** 429 를 맞은 키는 쉬게 하고 같은 요청을 다음 키로 보냅니다. 사용자는 아무것도 못 느낍니다.
   쉬는 시간은 응답의 `RetryInfo.retryDelay` 를 따르고, 없으면 한도 종류로 정합니다 — 분당 한도 60초, 일일 한도 1시간(그 뒤 다시 찔러봄).
   쉬는 상태는 **Redis 에 두어 ECS 태스크 여러 개가 같이 압니다.** 안 그러면 죽은 키를 인스턴스마다 다시 때립니다.
2. **모든 키가 막혔지만 근거는 찾은 경우 → 대체 답변.** 문장은 못 쓰지만 검색은 됐으므로, 찾은 근거를 출처와 함께
   그대로 보여주고 치료영역은 근거 청크의 K-DST 영역 → `area_mapping` 으로 뽑습니다. **기관 추천까지 이어집니다.**
   `fallback_tier=2`, `model='fallback'` 로 남습니다.
3. **검색조차 못 한 경우 → 503 `LLM_RATE_LIMITED`** (`details.retry_after_sec`). 임베딩도 답변 키를 쓰기 때문에
   처음 보는 질문은 여기로 옵니다. 같은 문장을 전에 물었다면 임베딩 캐시(7일)가 있어 2번으로 갑니다.
4. **요약 키가 막힌 경우 → 조용히 넘어갑니다.** 사용자와 무관하고, 나중에 채워 넣을 수 있습니다.

`GET /health` 가 지금 어느 키가 쉬는 중인지 보여줍니다. 키 값은 해시 앞 8자만 나옵니다.

```json
{"ok": true, "redis": true,
 "gemini": {"answer":  {"total": 2, "available": 1, "keys": [{"key":"ddc063f1","resting":true}, …]},
            "summary": {"total": 1, "available": 1, "keys": […]}}}
```

---

## Redis

없어도 API 는 그대로 돕니다(`REDIS_URL` 미설정 시 조용히 비활성).

| 용도 | TTL |
|---|---|
| 지역·기관 목록/상세 캐시 | 10분 |
| 질문 임베딩 캐시 (같은 문장 재질문 시 Gemini 호출 생략) | 7일 |
| 추천 칩 회전 카운터 | — |
| IP 당 질문 상한 (기본 60회/시간) | 1시간 |
| 답변 본문 임시 보관 (👍👎 누르면 학습 표본으로 이동) | 24시간 |
| 한도에 걸린 Gemini 키 휴식 표시 (인스턴스 간 공유) | 60초~1시간 |

---

## 배포

ECS(Fargate) + ECR 위에 올리고, 퍼블릭 서브넷의 EC2 한 대가 nginx 리버스 프록시 겸 SSM 배스천 역할을 합니다.
SSH 포트를 열지 않고 IAM 권한만으로 접속·포트포워딩합니다. 자세한 내용과 비용 추정은 [`infra/README.md`](infra/README.md).

```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars   # gemini_api_key 등
terraform init && terraform apply
../scripts/first-push.sh                       # 첫 이미지
../scripts/db-tunnel.sh                        # 터널 (다른 터미널에서 db-init.sh)
```

---

## 라이선스·이용 주의

- 기관 데이터는 공공데이터포털·보건복지부·사회보장정보원·가격 공시 등 공개 출처에서 받았습니다. 각 출처의 이용조건을 따릅니다.
- 지식베이스는 국가기관 자료를 정리한 2차 저작물입니다. 서비스로 공개하기 전 각 출처의 이용조건 확인이 필요합니다.
- 이 서비스는 **의료 진단을 제공하지 않습니다.** 걱정되는 점은 소아청소년과나 발달클리닉에서 확인해야 합니다.
