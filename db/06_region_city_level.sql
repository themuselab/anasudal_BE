-- 지역 선택 단위를 시·군·구 한 층으로 맞춘다.
--
-- 지금은 218개 중 6개만 구까지 쪼개져 있다 — 고양시(덕양·일산동·일산서),
-- 용인시(기흥·수지·처인). 나머지 통합시(성남·수원·안산·안양·창원·포항·천안·청주·전주)는
-- 전부 시 단위 한 행이다. 그래서 분당구에 사는 부모는 "성남시"를 고르는데, 일산에 사는
-- 부모는 "고양시"가 없어서 덕양/일산동/일산서 중에 골라야 한다. 같은 화면에서 층이 다르다.
--
-- 적은 쪽(6행)을 많은 쪽에 맞춘다. 구 단위로 통일하려면 9개 시를 전부 쪼개야 하는데,
-- 공시 데이터에 구 정보가 없어서 기관을 구에 배정할 방법이 없다.
BEGIN;

CREATE TEMP TABLE split_region ON COMMIT DROP AS
SELECT region_id, sido, split_part(sigungu, ' ', 1) AS city
FROM region
WHERE sigungu LIKE '% %구';

-- (시·도, 시) 마다 한 행만 남긴다. 대표는 가장 작은 region_id
CREATE TEMP TABLE kept_region ON COMMIT DROP AS
SELECT sido, city, min(region_id) AS keep_id
FROM split_region GROUP BY sido, city;

UPDATE institution i SET region_id = k.keep_id, updated_at = now()
FROM split_region t JOIN kept_region k ON k.sido = t.sido AND k.city = t.city
WHERE i.region_id = t.region_id AND i.region_id <> k.keep_id;

UPDATE session s SET region_id = k.keep_id
FROM split_region t JOIN kept_region k ON k.sido = t.sido AND k.city = t.city
WHERE s.region_id = t.region_id AND s.region_id <> k.keep_id;

UPDATE region r SET sigungu = k.city
FROM kept_region k WHERE r.region_id = k.keep_id;

DELETE FROM region r
USING split_region t JOIN kept_region k ON k.sido = t.sido AND k.city = t.city
WHERE r.region_id = t.region_id AND r.region_id <> k.keep_id;

COMMIT;

SELECT refresh_all_mvs();
