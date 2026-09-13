-- 지식베이스 청크의 domain 값 중 area_mapping 에 없던 것들을 채운다.
-- Gemini 키가 모두 한도에 걸렸을 때 LLM 없이 치료영역을 뽑는 경로(대체 답변)에서 쓴다.
-- evidence='draft' — 전문가 검토 전이라는 뜻. 검토 후 'source' 로 올릴 것.

INSERT INTO area_mapping (kdst_domain, area_code, priority, rationale, evidence) VALUES
  ('운동',     'MOTOR',    1, '대근육·소근육을 아우르는 운동 영역 → 운동발달재활이 1차',            'draft'),
  ('운동',     'PSYMOTOR', 2, '움직임과 심리 반응을 함께 다루는 심리운동이 보조',                   'draft'),
  ('사회정서', 'PLAY',     1, '또래 상호작용·정서 조절은 놀이심리재활이 1차',                       'draft'),
  ('사회정서', 'PSYCH',    2, '정서 문제 동반 시 재활심리 병행',                                    'draft'),
  ('조음',     'SPEECH',   1, '발음·조음은 언어재활 영역',                                          'draft')
ON CONFLICT (kdst_domain, area_code) DO NOTHING;
