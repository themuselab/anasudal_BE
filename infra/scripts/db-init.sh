#!/usr/bin/env bash
# 터널(db-tunnel.sh)이 열린 상태에서 실행. 스키마 생성 → CSV 적재 → MV 갱신.
# 사용: infra/scripts/db-init.sh [csv_dir]   (기본 ../../data)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
CSV_DIR="${1:-$ROOT/data}"
LOCAL_PORT="${LOCAL_PORT:-15432}"

cd "$ROOT/infra/terraform"
PARAM=$(terraform output -raw ssm_database_url_param)
REGION=$(terraform output -raw region 2>/dev/null || echo ap-northeast-2)

# SSM에 저장된 DSN에서 호스트만 localhost 터널로 바꿔 쓴다
DSN=$(aws ssm get-parameter --region "$REGION" --name "$PARAM" --with-decryption --query Parameter.Value --output text)
DSN_LOCAL=$(echo "$DSN" | sed -E "s#@[^:/]+:5432#@localhost:${LOCAL_PORT}#")

[ -f "$CSV_DIR/kb_chunks.csv" ] || { echo "kb_chunks.csv 없음 → python scripts/kb_to_csv.py 먼저"; exit 1; }

echo "1/2 schema"
psql "$DSN_LOCAL" -v ON_ERROR_STOP=1 -f "$ROOT/db/01_schema.sql"
echo "2/2 load  (csv_dir=$CSV_DIR)"
psql "$DSN_LOCAL" -v ON_ERROR_STOP=1 -v csv_dir="$CSV_DIR" -f "$ROOT/db/02_load.sql"
