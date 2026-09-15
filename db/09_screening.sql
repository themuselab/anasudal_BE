-- 조기 관찰(같이 살펴보기) — 과제 정의와 결과 보관
--
-- 근거
--   Bae et al., "Multimodal AI for risk stratification in autism spectrum disorder"
--   npj Digital Medicine (2025) 8:538. doi:10.1038/s41746-025-01914-6  (CC BY-NC-ND 4.0)
--   Kim et al., "Automated AI based identification of autism spectrum disorder from home videos"
--   npj Digital Medicine (2025). doi:10.1038/s41746-025-01993-5        (CC BY-NC-ND 4.0)
--   국내 9개 병원 510명(영상) / 1,242명(멀티모달), 18~48개월 대상 연구에서 쓰인
--   부모-아동 상호작용 과제를 집에서 해볼 수 있게 옮긴 것이다.
--
-- 판정하지 않는다
--   논문에서 과제 성공/실패만 쓴 모델은 AUROC 0.76 이고, 그것도 "고위험 vs 확진"을
--   가르는 2단계 과제였다. 0.93 은 SRS 설문 텍스트를 함께 넣었을 때의 값이고 그 설문은
--   우리가 쓸 수 없다. 우리에게는 그 조각 하나뿐이므로 위험도·점수·등급을 내지 않는다.
--   결과는 "오늘 이렇게 관찰됐다"는 기록이고, 판단은 전문기관이 한다.
--
-- 대사는 우리 표현으로 쓴다 (논문은 변경금지 조건이라 표 문구를 옮기지 않는다).

CREATE TABLE IF NOT EXISTS screening_task (
  task_code   varchar(16) PRIMARY KEY,
  title       text NOT NULL,
  age_lo      smallint NOT NULL,          -- 개월. 논문의 적용 연령 그대로
  age_hi      smallint NOT NULL,
  tool        text,                       -- 필요한 준비물. NULL 이면 맨몸으로 가능
  skippable   boolean NOT NULL DEFAULT false,
  observes    text NOT NULL,              -- 무엇을 보는 과제인지 (부모에게 보여줄 말)
  area_codes  text[] NOT NULL DEFAULT '{}',  -- 기관 추천용 치료영역. 팀 초안 — 전문가 검증 전
  sort_order  smallint NOT NULL DEFAULT 0,
  active      boolean NOT NULL DEFAULT true,
  CHECK (age_lo <= age_hi)
);
COMMENT ON TABLE screening_task IS '조기 관찰 과제. 연령 범위는 논문 Table 4 를 따른다';
COMMENT ON COLUMN screening_task.area_codes IS '판정 기준이 아니라 기관 필터용 부가 정보';

CREATE TABLE IF NOT EXISTS screening_step (
  task_code varchar(16) NOT NULL REFERENCES screening_task(task_code) ON DELETE CASCADE,
  step_no   smallint NOT NULL CHECK (step_no BETWEEN 1 AND 3),
  script    text NOT NULL,                -- 캐릭터 대사
  wait_sec  smallint NOT NULL DEFAULT 5,  -- 다음 단계로 넘어가기 전 기다리는 시간
  PRIMARY KEY (task_code, step_no)
);

CREATE TABLE IF NOT EXISTS screening_option (
  task_code varchar(16) NOT NULL REFERENCES screening_task(task_code) ON DELETE CASCADE,
  option_no smallint NOT NULL CHECK (option_no BETWEEN 1 AND 4),
  label     text NOT NULL,
  -- 1 에 가까울수록 또래에게 흔한 반응. 점수가 아니라 정렬·문장 생성에만 쓴다.
  PRIMARY KEY (task_code, option_no)
);

CREATE TABLE IF NOT EXISTS screening_result (
  result_token     uuid PRIMARY KEY DEFAULT gen_random_uuid(),   -- 추측 불가. 링크가 곧 열쇠
  child_age_months smallint NOT NULL CHECK (child_age_months BETWEEN 18 AND 48),
  answers          jsonb NOT NULL,          -- [{task_code, option_no}] — 스킵은 아예 안 담는다
  skipped          text[] NOT NULL DEFAULT '{}',  -- 준비물이 없어 건너뛴 과제. 신호와 절대 섞지 않는다
  area_codes       text[] NOT NULL DEFAULT '{}',  -- 반응이 약했던 과제의 영역 (기관 필터용)
  created_at       timestamptz NOT NULL DEFAULT now(),
  expires_at       timestamptz NOT NULL DEFAULT now() + interval '180 days'
);
CREATE INDEX IF NOT EXISTS screening_result_expires_idx ON screening_result(expires_at);
COMMENT ON TABLE screening_result IS
  '관찰 기록. 이름·지역·연락처 없음 — 아이 이름은 화면에서만 쓰고 서버로 보내지 않는다.
   링크를 아는 사람은 누구나 열 수 있으므로 180일 뒤 만료되고 본인이 지울 수 있다';
