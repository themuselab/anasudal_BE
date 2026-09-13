#!/usr/bin/env bash
# 카카오 플레이스 수집 결과(data/kakao_place.csv)를 운영 DB 에 반영한다.
#
#   bash scripts/apply_kakao_place.sh [csv경로]
#
# 안전장치
#   · 이미 값이 있는 칸은 덮어쓰지 않는다. 공공데이터·기존 값이 우선.
#   · 빈 문자열은 건너뛴다.
#   · 반영 전후 건수를 출력한다. (같으면 뭔가 잘못된 것)
#
# 전제: db-tunnel.sh 로 localhost:15432 터널이 열려 있을 것.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CSV="${1:-$ROOT/data/kakao_place.csv}"
PORT="${LOCAL_PORT:-15432}"

[ -f "$CSV" ] || { echo "파일이 없습니다: $CSV"; exit 1; }

PW=$(aws ssm get-parameter --name /anasudal/prod/DB_PASSWORD --with-decryption \
     --query Parameter.Value --output text)

HOST=host.docker.internal
MOUNT="$ROOT/data"
if command -v cygpath >/dev/null 2>&1; then MOUNT=$(cygpath -w "$MOUNT"); fi

psql_run () {
  # -i 없으면 컨테이너에 stdin 이 연결되지 않아 SQL 이 조용히 무시된다
  docker run --rm -i -e PGPASSWORD="$PW" -v "$MOUNT":/data postgres:16 \
    psql -h "$HOST" -p "$PORT" -U anasudal -d anasudal -v ON_ERROR_STOP=1 "$@"
}

echo "=== 반영 전 ==="
psql_run -At -c "select '  운영시간 '||count(operating_hours)||'/'||count(*)||'   홈페이지 '||count(homepage) from institution;"

echo "=== 반영 ==="
psql_run -f /dev/stdin <<SQL
begin;

create temp table kakao_place (
  biz_no text, operating_hours text, homepage text, note text
) on commit drop;

\copy kakao_place from '/data/$(basename "$CSV")' with (format csv, header true, encoding 'UTF8')

update institution i set operating_hours = p.operating_hours, updated_at = now()
from kakao_place p
where p.biz_no = i.biz_no
  and (i.operating_hours is null or i.operating_hours = '')
  and coalesce(p.operating_hours,'') <> '';

update institution i set homepage = p.homepage, updated_at = now()
from kakao_place p
where p.biz_no = i.biz_no
  and (i.homepage is null or i.homepage = '')
  and coalesce(p.homepage,'') <> '';

commit;
SQL

echo "=== 반영 후 ==="
psql_run -At -c "select '  운영시간 '||count(operating_hours)||'/'||count(*)||'   홈페이지 '||count(homepage) from institution;"

echo "=== 샘플 ==="
psql_run -At -F' | ' -c "select name, operating_hours from institution where operating_hours <> '' limit 5;"

echo "=== 기관 카드 MV 갱신 ==="
psql_run -At -c "select refresh_all_mvs();" >/dev/null && echo "  완료"
