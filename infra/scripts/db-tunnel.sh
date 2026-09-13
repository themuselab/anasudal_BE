#!/usr/bin/env bash
# Postgres 는 게이트웨이 EC2 안 컨테이너에서 돌고 127.0.0.1 에만 바인딩돼 있다.
# 밖에서는 어떤 경로로도 닿지 않는다. SSM 포트포워딩으로 로컬 15432 → 인스턴스 5432 를 연다.
#
# 사용: infra/scripts/db-tunnel.sh
#       (터널이 열린 상태에서 다른 터미널로 db-init.sh 나 psql 실행)
set -euo pipefail
cd "$(dirname "$0")/../terraform"

INSTANCE_ID=$(terraform output -raw gateway_instance_id)
REGION=$(terraform output -raw region 2>/dev/null || echo ap-northeast-2)
LOCAL_PORT="${LOCAL_PORT:-15432}"

echo "→ localhost:${LOCAL_PORT}  ⇢  ${INSTANCE_ID} 의 127.0.0.1:5432"
echo "  (끊으려면 Ctrl+C. 이 창은 열어둔 채로 다른 터미널에서 작업하세요)"

# 인스턴스 자신의 localhost 로 보내는 것이므로 ToRemoteHost 가 아닌 기본 문서를 쓴다
aws ssm start-session \
  --region "$REGION" \
  --target "$INSTANCE_ID" \
  --document-name AWS-StartPortForwardingSession \
  --parameters "{\"portNumber\":[\"5432\"],\"localPortNumber\":[\"${LOCAL_PORT}\"]}"
