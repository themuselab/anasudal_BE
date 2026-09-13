-- ============================================================================
--  안아수달 1차 MVP — PostgreSQL (Amazon RDS) 스키마
--  대상: PostgreSQL 15+ / pgvector 0.5+ (RDS는 rds_superuser로 확장 생성 가능)
--  원칙: 회원 테이블 없음 · 대화 원문 저장 안 함 · 기관 PK = 사업자등록번호
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS vector;      -- 임베딩 (768차원)
CREATE EXTENSION IF NOT EXISTS pgcrypto;    -- gen_random_uuid()

-- ─────────────────────────────────────────────────────────────
-- 공통 코드
-- ─────────────────────────────────────────────────────────────

CREATE TABLE region (
  region_id    smallserial PRIMARY KEY,
  sido         text NOT NULL,                     -- 서울특별시
  sigungu      text NOT NULL,                     -- 노원구
  legal_code   varchar(10),                       -- 행안부 법정동코드 (선택, 추후 매핑)
  UNIQUE (sido, sigungu)
);
COMMENT ON TABLE region IS '시·도/시·군·구. 위치 설정과 기관 소재지의 공통 키';

CREATE TABLE therapy_area (
  area_code       varchar(12) PRIMARY KEY,        -- SPEECH, SENSORY ...
  name            text NOT NULL UNIQUE,           -- 언어재활 (broso 공시 표기와 동일)
  description     text,                           -- 부모용 설명
  official_group  text,                           -- 언어·청능 / 미술·음악 / 행동·놀이·심리 / 감각·운동
  sort_order      smallint NOT NULL DEFAULT 0
);
COMMENT ON TABLE therapy_area IS '발달재활서비스 법정 치료영역 10종 + 기타. 기관 태그·매핑·입력이 모두 이 코드를 쓴다 (D-1 공통 코드)';

-- ─────────────────────────────────────────────────────────────
-- 기관
-- ─────────────────────────────────────────────────────────────

CREATE TABLE institution (
  biz_no           varchar(16) PRIMARY KEY,       -- 사업자등록번호 '123-45-67890', 분원은 '(1)','(2)' 접미
  name             text NOT NULL,
  region_id        smallint REFERENCES region(region_id),
  address          text,
  tel              varchar(20),                   -- 지역번호 검증 통과분만
  email            text,
  lat              numeric(9,6),
  lon              numeric(9,6),
  homepage         text,                          -- 기관 자체 홈페이지 (카카오 상세에서 확보)
  place_url        text,                          -- 카카오 플레이스 URL
  visit_available  boolean NOT NULL DEFAULT false,
  operating_hours  text,                          -- 공공 출처 없음 → 현재 전부 NULL (화면에서 행 숨김)
  match_conf       varchar(24),                   -- STRICT / ADDR / *_TEL_MISMATCH / NONE
  src              text,                          -- 결합 출처 플래그 'broso+mohw+ssis'
  updated_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX institution_region_idx ON institution(region_id);
CREATE INDEX institution_name_idx   ON institution(name text_pattern_ops);   -- 가나다 정렬·검색
COMMENT ON TABLE institution IS '전국 발달재활 제공기관 (broso 2026 가격공시 기준 2,866곳)';

CREATE TABLE institution_area_price (
  biz_no         varchar(16) NOT NULL REFERENCES institution(biz_no) ON DELETE CASCADE,
  area_code      varchar(12) NOT NULL REFERENCES therapy_area(area_code),
  delivery_mode  varchar(8)  NOT NULL CHECK (delivery_mode IN ('기관내','방문')),
  price_year     smallint    NOT NULL,            -- 2026
  price_krw      integer     NOT NULL CHECK (price_krw > 0),
  disclosed_at   date,                            -- 공시 기준일
  PRIMARY KEY (biz_no, area_code, delivery_mode, price_year)
);
CREATE INDEX iap_area_year_idx ON institution_area_price(area_code, price_year);
COMMENT ON TABLE institution_area_price IS '기관 × 치료영역 × 제공방식 × 연도 단가. 와이어프레임 "비용(특화분야별)" 표 그 자체';

-- ─────────────────────────────────────────────────────────────
-- 지식베이스 (RAG)
-- ─────────────────────────────────────────────────────────────

CREATE TABLE kb_source (
  source_id   serial PRIMARY KEY,
  publisher   text NOT NULL,                      -- 질병관리청
  title       text NOT NULL,                      -- 한국 영유아 발달선별검사(K-DST) 개정판
  year        smallint,
  url         text,
  license     text,                               -- 공공누리 1유형 / 확인필요
  UNIQUE (publisher, title)
);

CREATE TABLE kb_chunk (
  chunk_id    varchar(64) PRIMARY KEY,            -- kdst_60_언어_3, redflag_24개월 ...
  source_id   integer NOT NULL REFERENCES kb_source(source_id),
  chunk_type  varchar(32) NOT NULL,               -- developmental_milestone / red_flag / policy ...
  content     text NOT NULL,                      -- 카드 본문 (임베딩 대상)
  age_lo      smallint,                           -- 월령 필터 (NULL이면 전 연령)
  age_hi      smallint,
  domain      varchar(16),                        -- K-DST 영역: 언어·인지·사회성·대근육·소근육·자조
  meta        jsonb NOT NULL DEFAULT '{}'::jsonb,
  embedding   vector(768),                        -- gemini-embedding-2, RETRIEVAL_DOCUMENT
  CHECK (age_lo IS NULL OR age_hi IS NULL OR age_lo <= age_hi)
);
CREATE INDEX kb_chunk_type_idx ON kb_chunk(chunk_type);
CREATE INDEX kb_chunk_age_idx  ON kb_chunk(age_lo, age_hi) WHERE age_lo IS NOT NULL;
CREATE INDEX kb_chunk_meta_idx ON kb_chunk USING gin (meta);
-- 벡터 검색: HNSW + 코사인. 1,473행이라 ef_construction 기본값으로 충분
CREATE INDEX kb_chunk_embedding_idx ON kb_chunk
  USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);
COMMENT ON TABLE kb_chunk IS '검색 단위 카드 1,473장. 원본 필드는 age_lo/age_hi/domain/meta로 보존';

CREATE TABLE area_mapping (
  kdst_domain  varchar(16) NOT NULL,              -- 언어 / 사회성 / 소근육운동 ...
  area_code    varchar(12) NOT NULL REFERENCES therapy_area(area_code),
  priority     smallint NOT NULL CHECK (priority IN (1,2)),
  rationale    text,
  evidence     varchar(8) NOT NULL CHECK (evidence IN ('source','draft')),
  PRIMARY KEY (kdst_domain, area_code)
);
COMMENT ON TABLE area_mapping IS 'K-DST 영역 → 치료영역 우선순위. evidence=source는 국가건강정보포털 치료법 기술 근거, draft는 전문가 검증 대기';

-- ─────────────────────────────────────────────────────────────
-- 런타임 (세션·답변·피드백) — 개인정보 열 없음, 원문 열 없음
-- ─────────────────────────────────────────────────────────────

CREATE TABLE session (
  session_id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  region_id         smallint REFERENCES region(region_id),   -- 위치 설정 시
  child_age_months  smallint CHECK (child_age_months BETWEEN 0 AND 216),
  created_at        timestamptz NOT NULL DEFAULT now(),
  expires_at        timestamptz NOT NULL DEFAULT now() + interval '24 hours'
);
CREATE INDEX session_expires_idx ON session(expires_at);
COMMENT ON TABLE session IS '익명 세션. 로그인 없음. 만료 후 CASCADE 삭제';

CREATE TABLE answer (
  answer_id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id       uuid NOT NULL REFERENCES session(session_id) ON DELETE CASCADE,
  created_at       timestamptz NOT NULL DEFAULT now(),
  extracted_areas  jsonb NOT NULL DEFAULT '[]'::jsonb,   -- [{"area_code":"SPEECH","priority":1}, ...]
  intent_keywords  text[] NOT NULL DEFAULT '{}',         -- 원문 대신 키워드 ('수면','편식')
  fallback_tier    smallint NOT NULL CHECK (fallback_tier IN (1,2,3)),
  top_k            smallint NOT NULL DEFAULT 3,
  model            text,
  question_summary text                  -- 원문 대신: 생성 시 함께 만든 40자 내 요약 (신원 정보 없음)
);
CREATE INDEX answer_session_idx  ON answer(session_id);
CREATE INDEX answer_tier_idx     ON answer(fallback_tier, created_at);
CREATE INDEX answer_keywords_idx ON answer USING gin (intent_keywords);
COMMENT ON TABLE answer IS 'AI 답변 1건. 사용자 질문 원문·답변 원문 열이 의도적으로 없음';
COMMENT ON COLUMN answer.fallback_tier IS '1 근거 있음 / 2 부분 히트 / 3 범위 밖(진료 안내로 전환)';

CREATE TABLE answer_evidence (
  answer_id   uuid NOT NULL REFERENCES answer(answer_id) ON DELETE CASCADE,
  chunk_id    varchar(64) NOT NULL REFERENCES kb_chunk(chunk_id),
  rank        smallint NOT NULL CHECK (rank BETWEEN 1 AND 10),
  similarity  numeric(5,4) NOT NULL,              -- 코사인 유사도, 화면엔 ×100 정수
  PRIMARY KEY (answer_id, chunk_id)
);
CREATE INDEX answer_evidence_chunk_idx ON answer_evidence(chunk_id);

CREATE TABLE answer_recommendation (
  answer_id  uuid NOT NULL REFERENCES answer(answer_id) ON DELETE CASCADE,
  biz_no     varchar(16) NOT NULL REFERENCES institution(biz_no),
  rank       smallint NOT NULL CHECK (rank BETWEEN 1 AND 3),
  reason     text,                                -- AI가 구조화 데이터로 쓴 "왜 이 기관인가"
  PRIMARY KEY (answer_id, biz_no)
);
CREATE INDEX answer_recommendation_biz_idx ON answer_recommendation(biz_no);

CREATE TABLE feedback_reason (
  reason_code  varchar(16) PRIMARY KEY,
  label        text NOT NULL,
  sort_order   smallint NOT NULL DEFAULT 0
);

CREATE TABLE feedback (
  feedback_id  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  answer_id    uuid NOT NULL REFERENCES answer(answer_id) ON DELETE CASCADE,
  rating       varchar(4) NOT NULL CHECK (rating IN ('up','down')),
  reason_code  varchar(16) REFERENCES feedback_reason(reason_code),
  created_at   timestamptz NOT NULL DEFAULT now(),
  CHECK (rating = 'up' OR reason_code IS NOT NULL),     -- down이면 사유 필수
  UNIQUE (answer_id)                                    -- 답변당 1회
);

-- 학습 표본 — 👍👎가 눌린 답변만. 질문은 원문이 아니라 요약.
CREATE TABLE training_sample (
  sample_id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  answer_id         uuid UNIQUE REFERENCES answer(answer_id) ON DELETE SET NULL,  -- 세션 정리 뒤에도 표본은 남긴다
  rating            varchar(4) NOT NULL CHECK (rating IN ('up','down')),
  reason_code       varchar(16) REFERENCES feedback_reason(reason_code),
  question_summary  text,                 -- "30개월, 두 단어 문장 못 만들고 호명 반응 약함"
  answer_text       text,                 -- AI 답변 본문 (Redis 보관분이 있을 때)
  child_age_months  smallint,
  fallback_tier     smallint,
  extracted_areas   jsonb,                -- [{"area_code":"SPEECH","priority":1}]
  intent_keywords   text[],
  evidence          jsonb,                -- [{"chunk_id":"ksied_w_7","rank":1,"similarity":0.83}]
  recommended       text[],               -- 추천된 biz_no 순서대로
  model             text,
  rated_at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX training_sample_rating_idx ON training_sample (rating, rated_at DESC);

-- 학습 데이터 내보내기용 (jsonl 로 덤프: \copy (SELECT row_to_json(v) FROM v_training_export v) TO 'train.jsonl')
CREATE OR REPLACE VIEW v_training_export AS
SELECT sample_id, rated_at, rating, reason_code, question_summary, answer_text, child_age_months,
       fallback_tier, extracted_areas, intent_keywords, evidence, recommended, model
FROM training_sample;

CREATE TABLE suggested_prompt (
  prompt_id   smallserial PRIMARY KEY,
  text        text NOT NULL,
  emoji       text NOT NULL DEFAULT '💬',     -- 칩 앞 아이콘. 프론트는 서버 값만 쓴다
  sort_order  smallint NOT NULL DEFAULT 0,
  active      boolean NOT NULL DEFAULT true
);

-- ─────────────────────────────────────────────────────────────
-- 머티리얼라이즈드 뷰
-- ─────────────────────────────────────────────────────────────

-- ① 기관 카드 — 둘러보기 리스트 · 추천 결과 · 상세 상단이 전부 이 한 줄을 읽는다
--    태그(area_codes) · 비용대(price_min/max) · 지역명을 미리 합쳐둔다
CREATE MATERIALIZED VIEW mv_institution_card AS
WITH latest AS (
  SELECT max(price_year) AS y FROM institution_area_price
)
SELECT
  i.biz_no,
  i.name,
  r.sido,
  r.sigungu,
  i.region_id,
  i.address,
  i.tel,
  i.lat,
  i.lon,
  COALESCE(i.homepage, i.place_url)            AS link_url,      -- 자체 홈피 우선, 없으면 플레이스
  (i.homepage IS NOT NULL)                     AS has_own_site,
  i.visit_available,
  i.operating_hours,
  i.match_conf,
  array_agg(DISTINCT p.area_code ORDER BY p.area_code)
    FILTER (WHERE p.area_code IS NOT NULL)     AS area_codes,
  array_agg(DISTINCT a.name ORDER BY a.name)
    FILTER (WHERE a.name IS NOT NULL)          AS area_names,
  count(DISTINCT p.area_code)                  AS area_count,
  min(p.price_krw)                             AS price_min,
  max(p.price_krw)                             AS price_max,
  max(p.price_year)                            AS price_year,
  max(p.disclosed_at)                          AS disclosed_at
FROM institution i
LEFT JOIN region r ON r.region_id = i.region_id
LEFT JOIN institution_area_price p
       ON p.biz_no = i.biz_no
      AND p.price_year = (SELECT y FROM latest)
LEFT JOIN therapy_area a ON a.area_code = p.area_code
GROUP BY i.biz_no, i.name, r.sido, r.sigungu, i.region_id, i.address, i.tel,
         i.lat, i.lon, i.homepage, i.place_url, i.visit_available,
         i.operating_hours, i.match_conf
WITH DATA;

CREATE UNIQUE INDEX mv_institution_card_pk   ON mv_institution_card(biz_no);   -- CONCURRENTLY 갱신용
CREATE INDEX mv_institution_card_region_idx  ON mv_institution_card(region_id, name);
CREATE INDEX mv_institution_card_sido_idx    ON mv_institution_card(sido, name);
CREATE INDEX mv_institution_card_areas_idx   ON mv_institution_card USING gin (area_codes);
CREATE INDEX mv_institution_card_price_idx   ON mv_institution_card(price_min);
COMMENT ON MATERIALIZED VIEW mv_institution_card IS
  '추천 쿼리: WHERE area_codes @> ARRAY[''SPEECH'',''SENSORY''] AND price_min <= 60000 AND sido = ''서울특별시''';

-- ② 근거 자료 카드 — "근거 자료 N건 보기" 화면용 (청크 + 출처 조인, 임베딩 제외)
CREATE MATERIALIZED VIEW mv_kb_evidence AS
SELECT
  c.chunk_id,
  c.chunk_type,
  c.content,
  c.age_lo,
  c.age_hi,
  c.domain,
  s.source_id,
  s.publisher,
  s.title       AS source_title,
  s.year        AS source_year,
  s.url         AS source_url,
  s.license
FROM kb_chunk c
JOIN kb_source s ON s.source_id = c.source_id
WITH DATA;
CREATE UNIQUE INDEX mv_kb_evidence_pk ON mv_kb_evidence(chunk_id);

-- ③ 지역 × 영역 커버리지 — "이 지역에 감각발달재활 기관 N곳" 안내, 빈 결과 사전 감지
CREATE MATERIALIZED VIEW mv_area_coverage AS
SELECT
  r.sido,
  r.sigungu,
  r.region_id,
  a.area_code,
  a.name                         AS area_name,
  count(DISTINCT i.biz_no)       AS institution_count,
  min(p.price_krw)               AS price_min,
  max(p.price_krw)               AS price_max
FROM institution i
JOIN region r ON r.region_id = i.region_id
JOIN institution_area_price p ON p.biz_no = i.biz_no
JOIN therapy_area a ON a.area_code = p.area_code
GROUP BY r.sido, r.sigungu, r.region_id, a.area_code, a.name
WITH DATA;
CREATE UNIQUE INDEX mv_area_coverage_pk ON mv_area_coverage(region_id, area_code);
CREATE INDEX mv_area_coverage_sido_idx ON mv_area_coverage(sido, area_code);

-- ④ 피드백·폴백 집계 — 고도화 루프 대시보드 (원문 없이 키워드·영역·티어만)
CREATE MATERIALIZED VIEW mv_feedback_summary AS
SELECT
  date_trunc('day', ans.created_at)::date            AS day,
  ans.fallback_tier,
  kw.keyword,
  count(DISTINCT ans.answer_id)                       AS answers,
  count(f.feedback_id) FILTER (WHERE f.rating='up')   AS ups,
  count(f.feedback_id) FILTER (WHERE f.rating='down') AS downs,
  mode() WITHIN GROUP (ORDER BY f.reason_code)        AS top_down_reason
FROM answer ans
LEFT JOIN LATERAL unnest(
  CASE WHEN cardinality(ans.intent_keywords) = 0 THEN ARRAY['(없음)'] ELSE ans.intent_keywords END
) AS kw(keyword) ON true
LEFT JOIN feedback f ON f.answer_id = ans.answer_id
GROUP BY 1, 2, 3
WITH DATA;
CREATE UNIQUE INDEX mv_feedback_summary_pk ON mv_feedback_summary(day, fallback_tier, keyword);
COMMENT ON MATERIALIZED VIEW mv_feedback_summary IS
  'tier=3 키워드 상위 = 다음에 채울 지식베이스 주제. downs 비율 높은 영역 = 매핑 재검토 대상';

-- ─────────────────────────────────────────────────────────────
-- 갱신 함수 · 만료 정리
-- ─────────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION refresh_all_mvs() RETURNS void LANGUAGE plpgsql AS $$
BEGIN
  REFRESH MATERIALIZED VIEW CONCURRENTLY mv_institution_card;
  REFRESH MATERIALIZED VIEW CONCURRENTLY mv_kb_evidence;
  REFRESH MATERIALIZED VIEW CONCURRENTLY mv_area_coverage;
  REFRESH MATERIALIZED VIEW CONCURRENTLY mv_feedback_summary;
END $$;
COMMENT ON FUNCTION refresh_all_mvs IS '정적 데이터 재적재 후 1회, 피드백 집계는 pg_cron 등으로 매시 호출';

CREATE OR REPLACE FUNCTION purge_expired_sessions() RETURNS integer LANGUAGE plpgsql AS $$
DECLARE n integer;
BEGIN
  DELETE FROM session WHERE expires_at < now();     -- answer/evidence/recommendation/feedback CASCADE
  GET DIAGNOSTICS n = ROW_COUNT;
  RETURN n;
END $$;
COMMENT ON FUNCTION purge_expired_sessions IS '세션 만료 시 대화 파생 데이터까지 삭제. mv_feedback_summary는 그 전에 갱신해 집계만 남긴다';

-- ─────────────────────────────────────────────────────────────
-- 시드 — 코드 테이블
-- ─────────────────────────────────────────────────────────────

INSERT INTO therapy_area (area_code, name, official_group, sort_order, description) VALUES
  ('SPEECH',   '언어재활',     '언어·청능',       1, '말이 늦거나 발음이 부정확하거나 의사소통이 어려운 아동의 언어 능력을 키우는 치료입니다. 표현언어(말하기)와 수용언어(알아듣기)를 함께 다룹니다.'),
  ('AUDIT',    '청능재활',     '언어·청능',       2, '소리를 듣고 구별하고 이해하는 능력을 훈련합니다. 언어가 늦을 때 청각 문제가 원인일 수 있어 함께 확인하는 경우가 많습니다.'),
  ('ART',      '미술심리재활', '미술·음악',       3, '그림과 만들기를 매개로 감정을 표현하게 돕습니다. 말로 표현하기 어려워하는 아동에게 적합합니다.'),
  ('MUSIC',    '음악재활',     '미술·음악',       4, '악기 연주와 노래, 리듬 활동으로 정서 조절과 상호작용을 돕습니다.'),
  ('PLAY',     '놀이심리재활', '행동·놀이·심리',  5, '놀이를 매개로 정서·행동 문제를 다룹니다. 또래관계가 어렵거나 불안이 높은 아동에게 많이 권합니다.'),
  ('BEHAV',    '행동발달재활', '행동·놀이·심리',  6, '반복 행동이나 자해, 공격성 등 특정 행동을 줄이고 필요한 행동을 익히도록 돕습니다.'),
  ('PSYCH',    '재활심리',     '행동·놀이·심리',  7, '심리 평가와 상담을 통해 정서적 어려움을 다룹니다.'),
  ('SENSORY',  '감각발달재활', '감각·운동',       8, '촉각·청각·전정 감각 등이 지나치게 예민하거나 둔감한 경우 감각을 조절하고 통합하도록 돕습니다.'),
  ('MOTOR',    '운동발달재활', '감각·운동',       9, '앉기·걷기·뛰기 같은 대근육과 손 사용 같은 소근육 기능을 향상시킵니다.'),
  ('PSYMOTOR', '심리운동',     '감각·운동',      10, '움직임 활동을 통해 신체·정서·인지 발달을 함께 촉진합니다.'),
  ('ETC',      '기타',         NULL,             99, '지자체가 별도로 인정한 재활 영역입니다.');

INSERT INTO feedback_reason (reason_code, label, sort_order) VALUES
  ('MISMATCH',   '요청한 내용이 아니에요', 1),
  ('UNCLEAR',    '이해하기 어려워요',    2),
  ('BAD_RECO',   '추천이 별로예요',      3);

-- 화면엔 3개만 보이지만 호출마다 회전(Redis 라운드로빈)하므로 넉넉히 둔다.
-- 모두 KB(K-DST·새싹과단비·건강정보포털·바우처 제도)나 기관 DB로 답할 수 있는 질문만.
INSERT INTO suggested_prompt (text, emoji, sort_order) VALUES
  ('아이가 말이 느린 것 같아요', '🗣️',                     1),
  ('근처 언어치료 기관 찾아줘', '🔍',                      2),
  ('또래와 어울리는 걸 어려워해요', '🧸',                  3),
  ('이름을 불러도 잘 쳐다보지 않아요', '👀',               4),
  ('옷 라벨이나 특정 촉감을 심하게 싫어해요', '🧦',        5),
  ('발달재활 바우처는 어떻게 신청하나요', '📋',            6),
  ('걷기가 또래보다 많이 늦어요', '🚶',                    7),
  ('눈맞춤이 잘 안 되는 것 같아요', '👁️',                  8),
  ('소리에 유난히 민감해요', '🔊',                         9),
  ('어린이집에서 발달 검사를 권유받았어요', '🏫',          10),
  ('발음이 불분명해서 알아듣기 어려워요', '💬',            11),
  ('놀이할 때 혼자만 놀아요', '🧩',                        12),
  ('치료 비용은 회기당 얼마나 드나요', '💰',               13),
  ('손으로 하는 놀이나 그리기를 어려워해요', '✏️',         14);

-- K-DST 영역 → 치료영역 매핑 (kb_mapping.csv 15행)
INSERT INTO area_mapping (kdst_domain, area_code, priority, rationale, evidence) VALUES
  ('언어',       'SPEECH',   1, '자폐·뇌성마비·다운증후군 공통으로 언어치료가 1차 개입',                'source'),
  ('언어',       'AUDIT',    2, '언어지연 시 청각 문제 배제 필요. 다운증후군은 전도성 난청이 흔함',     'source'),
  ('사회성',     'PLAY',     1, '자폐 치료법 중 발달적 놀이치료와 사회 기술 훈련이 대응',               'source'),
  ('사회성',     'BEHAV',    2, 'ABA가 사회적 상호작용과 적응 기능에 효과 보고',                        'source'),
  ('소근육운동', 'SENSORY',  1, '감각자극 처리 문제나 과민 시 감각통합치료. 뇌성마비 작업치료가 감각훈련 포함', 'source'),
  ('소근육운동', 'MOTOR',    2, '뇌성마비 작업치료가 팔·손 미세동작 기능을 다룸',                       'source'),
  ('대근육운동', 'MOTOR',    1, '뇌성마비 물리치료·신경발달치료·보이타치료·보행훈련이 대응',            'source'),
  ('대근육운동', 'PSYMOTOR', 2, '움직임 기반 발달 촉진',                                                'draft'),
  ('자조',       'BEHAV',    1, 'ABA가 적응 기능 향상에 효과. 뇌성마비 작업치료가 일상생활 동작훈련 포함', 'source'),
  ('자조',       'SENSORY',  2, '감각 예민이 일상생활 수행을 방해',                                     'draft'),
  ('인지',       'PSYCH',    1, '다운증후군 인지치료·특수교육이 대응',                                  'source'),
  ('인지',       'SPEECH',   2, '인지와 언어는 상호 영향',                                              'draft'),
  ('인지',       'PLAY',     2, '놀이를 매개로 한 인지 개입',                                           'draft'),
  ('사회성',     'ART',      2, '비언어적 정서표현 경로. 다운증후군은 시각적 학습 강점이 있어 유리',     'source'),
  ('사회성',     'MUSIC',    2, '집단 음악활동을 통한 상호작용',                                        'draft');

-- 지식베이스 출처 5종 (kb_chunks.jsonl의 source 문자열과 1:1)
INSERT INTO kb_source (source_id, publisher, title, year, url, license) VALUES
  (1, '질병관리청·보건복지부', '한국 영유아 발달선별검사(K-DST) 개정판', 2022,
      'https://www.kdca.go.kr', '공공저작물'),
  (2, '삼성복지재단·육아정책연구소', '새싹과단비 발달길잡이', 2026,
      'https://www.xn--vb0b95ij3kspcfxd.org', '확인필요(2차인용 포함)'),
  (3, '질병관리청', '국가건강정보포털', 2025,
      'https://health.kdca.go.kr', '공공누리(유형 확인)'),
  (4, '보건복지부', '사회서비스 전자바우처 — 발달재활서비스 사업안내', 2026,
      'https://www.socialservice.or.kr', '공공저작물'),
  (5, '안아수달', '자체 매핑 초안 (전문가 자문 검증 필요)', 2026, NULL, '내부');
SELECT setval('kb_source_source_id_seq', 5);
