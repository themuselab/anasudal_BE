-- ============================================================================
--  학습 표본 — 👍👎가 눌린 답변만. 질문은 원문이 아니라 생성 시 함께 만든 1문장 요약.
--  (01_schema.sql 에도 포함. 이미 만든 DB에는 이 파일만 한 번 실행)
-- ============================================================================

ALTER TABLE answer ADD COLUMN IF NOT EXISTS question_summary text;   -- 40자 내 요약, 신원 정보 없음

CREATE TABLE IF NOT EXISTS training_sample (
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
CREATE INDEX IF NOT EXISTS training_sample_rating_idx ON training_sample (rating, rated_at DESC);

-- 학습 데이터 내보내기용 (jsonl 로 덤프: \copy (SELECT row_to_json(v) FROM v_training_export v) TO 'train.jsonl')
CREATE OR REPLACE VIEW v_training_export AS
SELECT sample_id, rated_at, rating, reason_code, question_summary, answer_text, child_age_months,
       fallback_tier, extracted_areas, intent_keywords, evidence, recommended, model
FROM training_sample;
