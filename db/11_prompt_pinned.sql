-- 첫 화면 칩 하나를 고정한다.
--
-- 지금은 14개에서 3개를 돌려 쓰는데, 관찰로 들어오는 입구가 매번 보이지 않으면
-- 기능이 있는 줄도 모른다. 하나는 항상 자리를 지키고 나머지 두 자리만 회전한다.
--
-- 문구에 나이를 넣지 않는다. "30개월 아이가…" 같은 칩은 그 나이가 아닌 부모에게는
-- 남의 이야기가 되고, 우리가 아이 나이를 단정하는 꼴이기도 하다.
ALTER TABLE suggested_prompt
  ADD COLUMN IF NOT EXISTS pinned boolean NOT NULL DEFAULT false;

CREATE INDEX IF NOT EXISTS suggested_prompt_pinned_idx
  ON suggested_prompt(slot, pinned, sort_order) WHERE active;

INSERT INTO suggested_prompt (text, emoji, sort_order, slot, pinned) VALUES
  ('우리 아이, 잘 자라고 있는 걸까요?', '🌱', 0, 'home', true)
ON CONFLICT DO NOTHING;

-- 고정 칩은 하나만. 여러 개면 회전할 자리가 남지 않는다.
UPDATE suggested_prompt SET pinned = false
WHERE slot = 'home' AND pinned AND text <> '우리 아이, 잘 자라고 있는 걸까요?';
