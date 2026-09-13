# 안아수달 백엔드

FastAPI + PostgreSQL(pgvector). 도메인별로 `router / service / repository / schemas` 4파일.

```
backend/
  app/
    main.py                 라우터 마운트, CORS, 풀 수명
    core/   config.py · db.py(asyncpg+pgvector) · gemini.py(임베딩·생성 REST)
    domains/
      region/       시·도 / 시·군·구
      institution/  둘러보기 · 상세 · 추천 쿼리
      knowledge/    벡터 검색 · 근거 카드
      chat/         세션 · 질문→답변 · 근거 · 추천 · 프롬프트 칩
      feedback/     👍👎 + 사유
  docker-compose.yml        로컬 pgvector (DDL 자동 적용)
```

## 1. DB 띄우기

```bash
cd backend
docker compose up -d            # ../db/01_schema.sql 자동 실행 (테이블·MV·시드)
```

RDS라면 `psql "$DATABASE_URL" -f ../db/01_schema.sql` 한 번. pgvector는 RDS PostgreSQL 15.2+에서 `CREATE EXTENSION vector` 가능.

## 2. 데이터 적재

```bash
cd ..
python scripts/kb_to_csv.py                          # data/kb_chunks.csv 생성 (벡터 포함)
psql "postgresql://anasudal:anasudal@localhost:5432/anasudal" \
     -v csv_dir="$PWD/data" -f db/02_load.sql
```

적재 대상: `nationwide_master.csv`(2,866) · `broso_price_nationwide_raw.csv`(13,352 → 중복 공시 합쳐 12,925) · `kb_chunks.csv`(1,473). 끝에 MV 4개를 갱신한다.

로컬에 psql이 없으면 컨테이너 안의 psql로 (Windows PowerShell 기준):

```powershell
docker exec anasudal-db mkdir -p /load
foreach ($f in "data/nationwide_master.csv","data/broso_price_nationwide_raw.csv","data/kb_chunks.csv","db/02_load.sql") {
  docker cp $f "anasudal-db:/load/$(Split-Path $f -Leaf)" }
docker exec anasudal-db psql -U anasudal -d anasudal -v ON_ERROR_STOP=1 -v csv_dir=/load -f /load/02_load.sql
```

## 3. API 실행

```bash
cd backend
cp .env.example .env            # GEMINI_API_KEY 채우기
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
# http://localhost:8000/docs
```

컨테이너로 실행할 때 (ECS와 같은 이미지):

```bash
docker build -t anasudal/api:local .
docker run -d --name anasudal-api --network backend_default -p 8000:8000 \
  -e DATABASE_URL=postgresql://anasudal:anasudal@db:5432/anasudal \
  -e REDIS_URL=redis://redis:6379/0 \
  -e CORS_ORIGINS=http://localhost:3000 \
  -e GEMINI_API_KEY=... anasudal/api:local
python ../scripts/smoke_api.py          # 화면 흐름 순서로 13개 호출 → data/raw/smoke_api.txt
```

생성 모델 기본값은 `models/gemini-3.6-flash` (2.5-flash는 신규 키에서 404). 임베딩은 KB를 만든 `gemini-embedding-2` 그대로여야 한다 — 바꾸면 벡터 공간이 달라져 검색이 깨진다.

## 4. 화면 ↔ 엔드포인트

| 화면 | 호출 |
|---|---|
| 첫 화면 칩 | `GET /v1/chat/prompts` — `{prompt_id, text, emoji}` 3개, 호출마다 회전 |
| 세션 시작 | `POST /v1/sessions` → `session_id` 를 브라우저에 보관 |
| 위치 설정 | `GET /regions/sido` → `PATCH /sessions/{id}` `{region_id}` |
| 둘러보기 | `GET /institutions?sido=서울특별시&page=1` (가나다순, 필터는 지역뿐) |
| 기관 상세 | `GET /institutions/{biz_no}` — `prices[]` 가 비용 표, `operating_hours` null이면 행 숨김 |
| 질문 | `POST /chat/ask` `{session_id, message}` → `text · areas · evidence_count · can_recommend · ask_region` |
| 근거 N건 | `GET /chat/answers/{answer_id}/evidence` — `match_percent` 가 "82% 일치" |
| 추천 | `POST /chat/recommend` `{session_id, answer_id, sido?}` → 3곳 + `reason` + `browse_hint` |
| 👍👎 | `POST /feedback` `{answer_id, rating, reason_code?}` · 사유 목록 `GET /feedback/reasons` |

## 5. 설계가 코드로 고정된 것

- **대화 원문은 어디에도 저장되지 않는다.** `answer` 에 원문 열이 없고 `intent_keywords`(명사 1~4개)와 `extracted_areas`(코드)만 남는다.
- **top_k = 3** (`.env`). 유사도 임계값은 없다 — 측정에서 관련/무관 분포가 겹쳐 컷이 불가했음.
- **진단 요구는 검색 전에 규칙으로 차단**(`chat/service.py::_DIAG`). 점수로는 못 거른다.
- **추천 사유는 LLM이 아니라 템플릿**(`_reason`). 구조화 데이터만 쓰므로 환각이 없다. 문장 다듬기가 필요하면 그때 LLM을 끼운다.
- **추천 순서 = 요구 영역과 겹치는 수 → 전 영역 포함 → 단가 → 이름.** 점수는 응답에 내보내지 않는다(회의 결정).

## 6. 빠른 확인

```bash
S=$(curl -s -X POST localhost:8000/v1/sessions -H 'content-type: application/json' -d '{}' | python -c "import sys,json;print(json.load(sys.stdin)['session_id'])")
curl -s -X POST localhost:8000/v1/chat/ask -H 'content-type: application/json' \
  -d "{\"session_id\":\"$S\",\"message\":\"6살인데 동생보다 말이 느린 것 같아요. 소리에 예민해요.\"}" | python -m json.tool
```

## 6. 추가 설계 (Redis · 지역 흐름 · 학습 표본)

**Redis** (`REDIS_URL`, 없으면 전부 조용히 꺼짐 — API는 그대로 동작)

| 용도 | 키 | TTL |
|---|---|---|
| 지역·기관 목록/상세 캐시 (MV 조회) | `anasudal:sido`, `sigungu:*`, `inst:*` | 10분 |
| 질문 임베딩 캐시 — 같은 문장 재질문 시 Gemini 임베딩 호출 생략 | `emb:<model>:<dim>:<task>:<sha>` | 7일 |
| 추천 칩 라운드로빈 카운터 (14개 중 3개씩, 호출마다 다른 묶음) | `prompts:rr` | 없음 |
| `/chat/ask` IP별 시간당 제한 (로그인 없음 → 남용 방지, 기본 30회) | `rl:ask:<ip>` | 1시간 |
| 답변 본문 임시 보관 — 👍👎가 눌리면 학습 표본으로 옮김 | `conv:<answer_id>` | 세션 TTL(24h) |

**지역은 추천 시점에 받는다** — 세션 생성 때는 지역 없음.
`/chat/ask` 응답의 `intent`로 프론트가 분기한다.

| intent | 언제 | 프론트 동작 |
|---|---|---|
| `answer` | 아이 설명에 근거 답변 | 본문 표시. 끝에 "기관을 추천해드릴까요?" · `can_recommend` 면 칩 "네, 추천해주세요" |
| `pick_region` | "추천해줘"인데 세션에 지역 없음 | 시·도→시·군·구 선택 UI → `/chat/recommend` 에 `region_id` (세션에 저장됨) |
| `recommend` | "추천해줘"이고 지역 있음 | 바로 `/chat/recommend` (`recommend_for` = 최근 근거 답변) |
| `need_context` | 아이 설명 없이 "추천해줘"부터 | 안내 문구 + 칩 |
| `diagnosis` / `out_of_scope` | 진단 요구 / 범위 밖 | 고정 문구 (Gemini 호출 없음 / 근거 0건) |

**키워드 볼드** — Gemini가 핵심 증상·영역을 마크다운 `**굵게**`로 표시하고, 서버가 치료영역명·키워드를 보강한다. `highlights[]`에 굵힌 단어 목록을 따로 준다.

**학습 표본 `training_sample`** — 👍👎가 눌린 답변만. 질문 원문 대신 생성 시 함께 만든 40자 요약(`answer.question_summary`, 신원 정보 제외) + 답변 본문 + 영역·키워드·근거(청크 id, 유사도)·추천 기관·평가·사유. `v_training_export` 뷰로 jsonl 덤프.

## 7. 응답 규격 · 에러 코드

모든 엔드포인트가 같은 봉투를 쓴다 (`/health` 제외). OpenAPI(/docs)의 스키마는 `data` 부분이다.

```json
{"success": true,  "data": { ... }}
{"success": false, "error": {"code": "FEEDBACK_REASON_REQUIRED", "message": "👎 에는 사유 선택이 필요합니다", "details": null}}
```

| HTTP | code | 언제 |
|---|---|---|
| 400 | `VALIDATION_ERROR` | 필드 누락·형식 오류. `details[].field / reason` |
| 400 | `FEEDBACK_REASON_REQUIRED` | 👎 인데 사유 없음 |
| 400 | `INVALID_REASON_CODE` | 사유 코드가 목록에 없음. `details.allowed` |
| 400 | `MESSAGE_EMPTY` | 질문이 공백 |
| 404 | `SESSION_NOT_FOUND` | 세션 없음·만료 (프론트: 세션 새로 발급) |
| 404 | `ANSWER_NOT_FOUND` / `REGION_NOT_FOUND` / `INSTITUTION_NOT_FOUND` / `CHUNK_NOT_FOUND` | |
| 404 | `NOT_FOUND` | 라우트 없음 |
| 409 | `ANSWER_NOT_GROUNDED` | tier 1이 아닌 답변으로 추천 요청 |
| 409 | `ANSWER_SESSION_MISMATCH` | 다른 세션의 답변 |
| 429 | `RATE_LIMITED` | IP당 시간당 질문 상한 |
| 503 | `LLM_RATE_LIMITED` | Gemini 분당 한도. 서버가 4초 대기 후 1회 재시도, 그래도 막히면 이 코드. `details.retry_after_sec` |
| 502 | `LLM_FAILED` | Gemini 실패 (1회 재시도 후). `details.cause` |
| 500 | `INTERNAL_ERROR` | 그 외 |

구현: `app/core/errors.py`(코드·핸들러) · `app/core/envelope.py`(성공 봉투, 각 라우터 `route_class`). 서비스 코드는 `raise ApiError(status, ErrorCode.X, message, details)`.

## 8. SSE 스트리밍 `POST /v1/chat/ask/stream`

요청은 `/chat/ask` 와 같고 응답은 `text/event-stream`. 프론트는 이걸 기본으로 쓴다.

```
event: meta   data: {"evidence_count": 3}          ← 검색 끝, 생성 시작
event: delta  data: {"text": "삼성복지재단…"}      ← 본문 조각 (모델 원문, 여러 번)
event: done   data: {AskResponse}                  ← 최종본. text 는 볼드·마무리 문장 반영 → 이걸로 교체
event: error  data: {"code": "LLM_RATE_LIMITED", "message": "…"}
```

- 진단 게이트·추천 라우팅처럼 생성이 없는 응답은 `done` 하나만 온다.
- 범위 밖(grounded=false)이면 본문 조각을 내보내지 않고 `done` 의 고정 문구만 온다.
- 스트림 시작 전 오류(429 등)는 일반 JSON 봉투로 온다. 스트림 중 오류는 `error` 이벤트.
- 구현: `core/gemini.py generate_json_stream` 이 Gemini `streamGenerateContent?alt=sse` 의 JSON 텍스트에서 `"answer"` 문자열만 점진 디코드. `service.ask_stream` 이 `ask` 와 같은 `_prepare/_finalize` 를 공유.
- 지연: `GEMINI_THINKING_LEVEL=low` (기본) 로 첫 글자 1.7s / 전체 2.8s. 기본 thinking 은 7.5s / 9s 였다.
- nginx 게이트웨이는 `/v1/` 에 `proxy_buffering off` (infra/terraform/templates/gateway-user-data.sh).
