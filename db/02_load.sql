-- ============================================================================
--  적재 스크립트 — CSV → 스테이징 → 본 테이블
--  실행: psql "$DATABASE_URL" -v csv_dir='/abs/path/to/data' -f db/02_load.sql
--  사전: scripts/kb_to_csv.py 로 kb_chunks.csv 생성 (jsonl + 벡터 → CSV)
-- ============================================================================

\set ON_ERROR_STOP on
-- \copy 는 변수 치환을 하지 않는다 → 명령 전체를 변수로 만들어 :var 한 줄로 실행
\set copy_inst  '\\copy stg_institution FROM ''' :csv_dir '/nationwide_master.csv'' WITH (FORMAT csv, HEADER true, ENCODING ''UTF8'')'
\set copy_price '\\copy stg_price FROM ''' :csv_dir '/broso_price_nationwide_raw.csv'' WITH (FORMAT csv, HEADER true, ENCODING ''UTF8'')'
\set copy_chunk '\\copy stg_chunk FROM ''' :csv_dir '/kb_chunks.csv'' WITH (FORMAT csv, HEADER true, ENCODING ''UTF8'')'
\echo '== 스테이징 테이블 =='

DROP TABLE IF EXISTS stg_institution;
CREATE TEMP TABLE stg_institution (
  biz_no text, name text, sido text, sigungu text, address text, tel text, email text,
  lat text, lon text, areas text, area_count text, price_min text, price_max text, visit text,
  specialty_extra text, operating_hours text, waiting text, severity text, age_range text,
  therapist_count text, homepage text, src text, kakao_category text, own_homepage text,
  photo text, match_conf text, programs_local text
);
:copy_inst

DROP TABLE IF EXISTS stg_price;
CREATE TEMP TABLE stg_price (
  sido text, sigungu text, name text, biz_no text, way text, area text, price text, src_file text
);
:copy_price

DROP TABLE IF EXISTS stg_chunk;
CREATE TEMP TABLE stg_chunk (
  chunk_id text, source_id text, chunk_type text, content text,
  age_lo text, age_hi text, domain text, meta text, embedding text
);
:copy_chunk

\echo '== region =='
INSERT INTO region (sido, sigungu)
SELECT DISTINCT btrim(sido), btrim(sigungu)
FROM stg_institution
WHERE sido <> '' AND sigungu <> ''
ON CONFLICT (sido, sigungu) DO NOTHING;

\echo '== institution =='
INSERT INTO institution (biz_no, name, region_id, address, tel, email, lat, lon,
                         homepage, place_url, visit_available, operating_hours, match_conf, src)
SELECT
  btrim(s.biz_no),
  btrim(s.name),
  r.region_id,
  NULLIF(btrim(s.address), ''),
  NULLIF(btrim(s.tel), ''),
  NULLIF(btrim(s.email), ''),
  NULLIF(s.lat, '')::numeric,
  NULLIF(s.lon, '')::numeric,
  NULLIF(btrim(s.own_homepage), ''),          -- 자체 홈페이지
  NULLIF(btrim(s.homepage), ''),              -- CSV의 homepage 열 = 카카오 플레이스 URL
  (COALESCE(s.visit, '') = 'Y'),             -- CSV 빈 필드는 NULL로 들어오므로
  NULLIF(btrim(s.operating_hours), ''),
  NULLIF(btrim(s.match_conf), ''),
  NULLIF(btrim(s.src), '')
FROM stg_institution s
LEFT JOIN region r ON r.sido = btrim(s.sido) AND r.sigungu = btrim(s.sigungu)
WHERE s.biz_no <> ''
ON CONFLICT (biz_no) DO UPDATE SET
  name = EXCLUDED.name, region_id = EXCLUDED.region_id, address = EXCLUDED.address,
  tel = EXCLUDED.tel, email = EXCLUDED.email, lat = EXCLUDED.lat, lon = EXCLUDED.lon,
  homepage = EXCLUDED.homepage, place_url = EXCLUDED.place_url,
  visit_available = EXCLUDED.visit_available, match_conf = EXCLUDED.match_conf,
  src = EXCLUDED.src, updated_at = now();

\echo '== institution_area_price =='
-- 같은 (기관, 영역, 방식)이 중복 공시된 경우 최고가 1건만 남긴다
INSERT INTO institution_area_price (biz_no, area_code, delivery_mode, price_year, price_krw, disclosed_at)
SELECT DISTINCT ON (btrim(p.biz_no), a.area_code, dm.mode)
  btrim(p.biz_no),
  a.area_code,
  dm.mode,
  2026,
  NULLIF(regexp_replace(p.price, '[^0-9]', '', 'g'), '')::int,
  DATE '2026-05-06'                             -- broso 게시일
FROM stg_price p
JOIN therapy_area a ON a.name = btrim(p.area)
JOIN institution i ON i.biz_no = btrim(p.biz_no)
CROSS JOIN LATERAL (SELECT CASE WHEN p.way LIKE '%방문%' THEN '방문' ELSE '기관내' END AS mode) dm
WHERE p.biz_no <> '' AND NULLIF(regexp_replace(p.price, '[^0-9]', '', 'g'), '') IS NOT NULL
ORDER BY btrim(p.biz_no), a.area_code, dm.mode, NULLIF(regexp_replace(p.price, '[^0-9]', '', 'g'), '')::int DESC
ON CONFLICT (biz_no, area_code, delivery_mode, price_year) DO UPDATE SET
  price_krw = EXCLUDED.price_krw, disclosed_at = EXCLUDED.disclosed_at;

\echo '== kb_chunk =='
INSERT INTO kb_chunk (chunk_id, source_id, chunk_type, content, age_lo, age_hi, domain, meta, embedding)
SELECT
  c.chunk_id,
  c.source_id::int,
  c.chunk_type,
  c.content,
  NULLIF(c.age_lo, '')::smallint,
  NULLIF(c.age_hi, '')::smallint,
  NULLIF(c.domain, ''),
  COALESCE(NULLIF(c.meta, ''), '{}')::jsonb,
  NULLIF(c.embedding, '')::vector
FROM stg_chunk c
ON CONFLICT (chunk_id) DO UPDATE SET
  content = EXCLUDED.content, meta = EXCLUDED.meta, embedding = EXCLUDED.embedding,
  age_lo = EXCLUDED.age_lo, age_hi = EXCLUDED.age_hi, domain = EXCLUDED.domain;

\echo '== MV 갱신 =='
SELECT refresh_all_mvs();

\echo '== 결과 =='
SELECT 'region' AS t, count(*) FROM region
UNION ALL SELECT 'institution', count(*) FROM institution
UNION ALL SELECT 'institution_area_price', count(*) FROM institution_area_price
UNION ALL SELECT 'kb_chunk', count(*) FROM kb_chunk
UNION ALL SELECT 'kb_chunk(embedded)', count(*) FROM kb_chunk WHERE embedding IS NOT NULL
UNION ALL SELECT 'mv_institution_card', count(*) FROM mv_institution_card;
