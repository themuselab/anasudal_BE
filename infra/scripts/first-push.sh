#!/usr/bin/env bash
# terraform apply 직후 ECR이 비어 있어 ECS 태스크가 뜨지 못한다. 첫 이미지를 로컬에서 밀어 넣는다.
# 이후는 GitHub Actions(.github/workflows/deploy.yml)가 담당.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT/infra/terraform"
REPO=$(terraform output -raw ecr_repository_url)
CLUSTER=$(terraform output -raw ecs_cluster)
SERVICE=$(terraform output -raw ecs_service)
REGION=$(terraform output -raw region 2>/dev/null || echo ap-northeast-2)
REGISTRY="${REPO%%/*}"

aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$REGISTRY"
docker build --platform linux/amd64 -t "$REPO:latest" "$ROOT/backend"
docker push "$REPO:latest"
aws ecs update-service --region "$REGION" --cluster "$CLUSTER" --service "$SERVICE" --force-new-deployment >/dev/null
echo "배포 시작. 상태: aws ecs describe-services --cluster $CLUSTER --services $SERVICE --query 'services[0].deployments'"
