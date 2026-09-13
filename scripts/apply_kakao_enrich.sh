#!/usr/bin/env bash
# 카카오 보강 결과(data/kakao_enrich.csv)를 운영 DB 에 반영한다.
#
#   bash scripts/apply_kakao_enrich.sh [csv경로]
#
# 안전장치
#   · 이미 값이 있는 칸은 덮어쓰지 않는다 (coalesce). 공공데이터 원본이 우선.
#   · ROAD(도로·동 중심점, 수백 m 오차) 는 기본적으로 제외한다.
#     포함하려면 INCLUDE_ROAD=1 로 실행.
#   · 반영 전후 건수를 출력한다.
#
# 전제: db-tunnel.sh 로 localhost:15432 터널이 열려 있을 것.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CSV="${1:-$ROOT/data/kakao_enrich.csv}"
PORT="${LOCAL_PORT:-15432}"
INCLUDE_ROAD="${INCLUDE_ROAD:-0}"

[ -f "$CSV" ] || { echo "파일이 없습니다: $CSV"; exit 1; }

PW=$(aws ssm get-parameter --name /anasudal/prod/DB_PASSWORD --with-decryption \
     --query Parameter.Value --output text)

# Docker Desktop(Windows)에서는 호스트 루프백을 host.docker.internal 로 본다
HOST=host.docker.internal
MOUNT="$ROOT/data"
if command -v cygpath >/dev/null 2>&1; then MOUNT=$(cygpath -w "$MOUNT"); fi

psql_run () {
  # -i 가 없으면 컨테이너에 stdin 이 연결되지 않아, -f /dev/stdin 으로 넘긴 SQL 이
  # 통째로 무시된다(오류도 없이 0건 처리됨). 반드시 있어야 한다.
  docker run --rm -i -e PGPASSWORD="$PW" -v "$MOUNT":/data postgres:16 \
    psql -h "$HOST" -p "$PORT" -U anasudal -d anasudal -v ON_ERROR_STOP=1 "$@"
}

echo "=== 반영 전 ==="
psql_run -At -c "select '  좌표 '||count(lat)||'/'||count(*)||'  전화 '||count(tel)||'  링크 '||count(place_url) from institution;"

ROAD_FILTER="and method <> 'ROAD'"
[ "$INCLUDE_ROAD" = "1" ] && ROAD_FILTER=""
echo "=== 반영 (ROAD 포함=$INCLUDE_ROAD) ==="

psql_run -f /dev/stdin <<SQL
begin;

create temp table kakao_enrich (
  biz_no text, lat text, lon text, tel text, place_url text, method text, query text
) on commit drop;

\copy kakao_enrich from '/data/$(basename "$CSV")' with (format csv, header true, encoding 'UTF8')

-- 좌표: 비어 있는 칸에만. ROAD(근사) 는 기본 제외.
update institution i set
  lat = e.lat::numeric,
  lon = e.lon::numeric,
  updated_at = now()
from kakao_enrich e
where e.biz_no = i.biz_no
  and i.lat is null
  and e.lat <> '' $ROAD_FILTER;

-- 전화: 비어 있는 칸에만
update institution i set tel = e.tel, updated_at = now()
from kakao_enrich e
where e.biz_no = i.biz_no and (i.tel is null or i.tel = '') and e.tel <> '';

-- 카카오맵 링크: 비어 있는 칸에만
update institution i set place_url = e.place_url, updated_at = now()
from kakao_enrich e
where e.biz_no = i.biz_no and (i.place_url is null or i.place_url = '') and e.place_url <> '';

commit;
SQL

echo "=== 반영 후 ==="
psql_run -At -c "select '  좌표 '||count(lat)||'/'||count(*)||'  전화 '||count(tel)||'  링크 '||count(place_url) from institution;"

echo "=== 기관 카드 MV 갱신 ==="
psql_run -At -c "select refresh_all_mvs();" >/dev/null && echo "  완료"
