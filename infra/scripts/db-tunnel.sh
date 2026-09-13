#!/usr/bin/env bash
# RDS는 프라이빗 서브넷에만 있다. 게이트웨이 EC2를 통해 SSM 포트포워딩으로 로컬 15432 → RDS 5432 를 연다.
# 사용: infra/scripts/db-tunnel.sh   (터널이 열린 상태에서 다른 터미널로 psql/02_load.sql 실행)
set -euo pipefail
cd "$(dirname "$0")/../terraform"

INSTANCE_ID=$(terraform output -raw gateway_instance_id)
RDS_HOST=$(terraform output -raw rds_endpoint)
REGION=$(terraform output -raw region 2>/dev/null || echo ap-northeast-2)
LOCAL_PORT="${LOCAL_PORT:-15432}"

echo "→ localhost:${LOCAL_PORT}  ⇢  ${RDS_HOST}:5432  (via ${INSTANCE_ID})"
aws ssm start-session \
  --region "$REGION" \
  --target "$INSTANCE_ID" \
  --document-name AWS-StartPortForwardingSessionToRemoteHost \
  --parameters "{\"host\":[\"${RDS_HOST}\"],\"portNumber\":[\"5432\"],\"localPortNumber\":[\"${LOCAL_PORT}\"]}"
