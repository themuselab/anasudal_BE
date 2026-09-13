#!/usr/bin/env bash
# 게이트웨이 EC2에 SSM 셸 접속 (SSH 키·22번 포트 없음). nginx 로그 확인 등.
set -euo pipefail
cd "$(dirname "$0")/../terraform"
aws ssm start-session \
  --region "$(terraform output -raw region 2>/dev/null || echo ap-northeast-2)" \
  --target "$(terraform output -raw gateway_instance_id)"
