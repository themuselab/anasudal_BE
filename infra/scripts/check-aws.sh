#!/usr/bin/env bash
# 자격 증명이 제대로 붙었는지, 이 프로젝트에 필요한 권한이 있는지 훑어본다.
# 사용: AWS_PROFILE=anasudal bash infra/scripts/check-aws.sh
set -uo pipefail

PROFILE="${AWS_PROFILE:-anasudal}"
export AWS_PROFILE="$PROFILE"
echo "프로필: $PROFILE"

if ! ARN=$(aws sts get-caller-identity --query Arn --output text 2>&1); then
  echo "✗ 인증 실패"; echo "$ARN" | head -3 | sed 's/^/    /'; exit 1
fi
echo "✓ 인증됨"
echo "  계정: $(aws sts get-caller-identity --query Account --output text)"
echo "  주체: $ARN"
echo "  리전: $(aws configure get region)"

echo
echo "── 권한 훑기 (읽기만) ─────────────────────────────"
probe () {  # 이름 / 명령
  local name="$1"; shift
  if "$@" >/dev/null 2>&1; then printf "  ✓ %s\n" "$name"; else printf "  ✗ %s\n" "$name"; fi
}
probe "EC2  조회"         aws ec2 describe-vpcs --max-items 1
probe "ECR  조회"         aws ecr describe-repositories --max-items 1
probe "ECS  조회"         aws ecs list-clusters --max-items 1
probe "RDS  조회"         aws rds describe-db-instances --max-items 1
probe "ElastiCache 조회"  aws elasticache describe-cache-clusters --max-items 1
probe "SSM  파라미터"     aws ssm describe-parameters --max-items 1
probe "IAM  역할 조회"    aws iam list-roles --max-items 1
probe "CloudWatch 로그"   aws logs describe-log-groups --max-items 1

echo
echo "── 계정에 이미 있는 것 (기존 프로젝트 확인용) ──────"
echo "  VPC:"
aws ec2 describe-vpcs \
  --query 'Vpcs[].{id:VpcId,cidr:CidrBlock,default:IsDefault,name:Tags[?Key==`Name`]|[0].Value,project:Tags[?Key==`Project`]|[0].Value}' \
  --output table 2>/dev/null || echo "    (조회 불가)"
echo "  ECS 클러스터:"
aws ecs list-clusters --query 'clusterArns' --output text 2>/dev/null | tr '\t' '\n' | sed 's/^/    /' || echo "    (조회 불가)"
echo "  RDS:"
aws rds describe-db-instances --query 'DBInstances[].DBInstanceIdentifier' --output text 2>/dev/null | tr '\t' '\n' | sed 's/^/    /' || echo "    (조회 불가)"
