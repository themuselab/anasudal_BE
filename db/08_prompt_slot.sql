-- 칩이 어디에 붙는지를 데이터로 둔다.
--
-- 첫 화면 칩은 이미 이 표에서 회전시켜 쓰는데, 답변 뒤에 붙는 후속 칩만 코드에
-- 문자열로 박혀 있었다. 문구를 바꾸려고 배포를 하게 된다. 같은 표에서 꺼내 쓴다.
--
--   home      첫 화면 (지금까지 있던 것 전부)
--   followup  답변 뒤 — 절차·제도 질문처럼 치료영역이 안 잡힌 답변에 붙는다
--
-- "네, 추천해주세요" 는 여기 넣지 않는다. 그건 문구가 아니라 동작이다 —
-- 서버의 추천 요청 정규식과 짝이라 문구를 바꾸면 흐름이 끊긴다.
ALTER TABLE suggested_prompt
  ADD COLUMN IF NOT EXISTS slot varchar(12) NOT NULL DEFAULT 'home';

ALTER TABLE suggested_prompt DROP CONSTRAINT IF EXISTS suggested_prompt_slot_chk;
ALTER TABLE suggested_prompt
  ADD CONSTRAINT suggested_prompt_slot_chk CHECK (slot IN ('home', 'followup'));

CREATE INDEX IF NOT EXISTS suggested_prompt_slot_idx
  ON suggested_prompt(slot, sort_order) WHERE active;

-- 후속 칩. 누르면 그 문장이 그대로 질문으로 전송되므로 실제로 답이 나오는 문장이어야 한다.
INSERT INTO suggested_prompt (text, emoji, sort_order, slot) VALUES
  ('아이가 말이 느린 것 같아요',        '🗣️', 1, 'followup'),
  ('또래와 어울리는 걸 어려워해요',      '🧸', 2, 'followup'),
  ('이름을 불러도 잘 쳐다보지 않아요',    '👀', 3, 'followup'),
  ('눈맞춤이 잘 안 되는 것 같아요',      '👁️', 4, 'followup'),
  ('소리에 유난히 민감해요',            '🔊', 5, 'followup')
ON CONFLICT DO NOTHING;
