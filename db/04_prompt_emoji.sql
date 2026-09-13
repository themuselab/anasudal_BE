-- 이미 만든 DB용: 칩 이모지 컬럼 + 값
ALTER TABLE suggested_prompt ADD COLUMN IF NOT EXISTS emoji text NOT NULL DEFAULT '💬';
UPDATE suggested_prompt SET emoji = '🗣️' WHERE text = '아이가 말이 느린 것 같아요';
UPDATE suggested_prompt SET emoji = '🔍' WHERE text = '근처 언어치료 기관 찾아줘';
UPDATE suggested_prompt SET emoji = '🧸' WHERE text = '또래와 어울리는 걸 어려워해요';
UPDATE suggested_prompt SET emoji = '👀' WHERE text = '이름을 불러도 잘 쳐다보지 않아요';
UPDATE suggested_prompt SET emoji = '🧦' WHERE text = '옷 라벨이나 특정 촉감을 심하게 싫어해요';
UPDATE suggested_prompt SET emoji = '📋' WHERE text = '발달재활 바우처는 어떻게 신청하나요';
UPDATE suggested_prompt SET emoji = '🚶' WHERE text = '걷기가 또래보다 많이 늦어요';
UPDATE suggested_prompt SET emoji = '👁️' WHERE text = '눈맞춤이 잘 안 되는 것 같아요';
UPDATE suggested_prompt SET emoji = '🔊' WHERE text = '소리에 유난히 민감해요';
UPDATE suggested_prompt SET emoji = '🏫' WHERE text = '어린이집에서 발달 검사를 권유받았어요';
UPDATE suggested_prompt SET emoji = '💬' WHERE text = '발음이 불분명해서 알아듣기 어려워요';
UPDATE suggested_prompt SET emoji = '🧩' WHERE text = '놀이할 때 혼자만 놀아요';
UPDATE suggested_prompt SET emoji = '💰' WHERE text = '치료 비용은 회기당 얼마나 드나요';
UPDATE suggested_prompt SET emoji = '✏️' WHERE text = '손으로 하는 놀이나 그리기를 어려워해요';
