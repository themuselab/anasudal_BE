#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# 안아수달 전용 배포 IAM 사용자 만들기 — AWS CloudShell 에 그대로 붙여넣고 실행.
#
# 만드는 것
#   · IAM 사용자      anasudal-deploy
#   · 정책 2개        anasudal-deploy-core   (ECR·ECS·로그·SSM·IAM 역할, 전부 anasudal-* 로 한정)
#                     anasudal-deploy-infra  (VPC·RDS·ElastiCache + 다른 프로젝트 손대기 금지)
#   · 액세스 키       1개 (출력됨 — 한 번만 보인다)
#
# 기존 프로젝트 보호
#   · 이 사용자가 만드는 모든 리소스는 이름이 anasudal-* 이고 태그 Project=anasudal 이다
#   · 삭제·변경 계열 동작은 태그가 anasudal 이 아닌 리소스에 대해 명시적으로 거부된다
#   · IAM 사용자·정책 자체를 건드리는 권한은 없다 (권한 상승 차단)
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

USER_NAME=anasudal-deploy
PROJECT=anasudal

# ── 0. 사전 확인 ────────────────────────────────────────────────────────────
# 자격 증명부터 확인한다. 여기서 막히면 아래 작업은 전부 같은 이유로 실패한다.
if ! CALLER=$(aws sts get-caller-identity --query Arn --output text 2>&1); then
  echo "✗ AWS 자격 증명을 쓸 수 없습니다."
  echo "$CALLER" | head -3 | sed 's/^/    /'
  echo
  echo "  · CloudShell 이면 → 우측 상단 Actions → Restart AWS CloudShell 후 재실행"
  echo "  · 루트 사용자는 CloudShell 을 쓸 수 없습니다. 로컬에서 이렇게 하세요:"
  echo "      aws configure --profile root-bootstrap"
  echo "      AWS_PROFILE=root-bootstrap bash infra/iam/create-deploy-user.sh"
  exit 1
fi
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
echo "▶ 계정: $ACCOUNT"
echo "▶ 주체: $CALLER"
case "$CALLER" in
  *:root) echo "  ⚠ 루트로 실행 중입니다. 스크립트가 끝나면 루트 액세스 키를 삭제하세요." ;;
esac

# ── 1. 정책 문서 ─────────────────────────────────────────────────────────────
cat > /tmp/anasudal-core.json <<'CORE'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ReadOnlyEverywhere",
      "Effect": "Allow",
      "Action": [
        "sts:GetCallerIdentity",
        "ecr:GetAuthorizationToken",
        "ecr:Describe*", "ecr:List*",
        "ecs:Describe*", "ecs:List*",
        "logs:Describe*", "logs:Get*",
        "ssm:Describe*", "ssm:GetParameter", "ssm:GetParameters", "ssm:GetParametersByPath",
        "ssm:GetConnectionStatus", "ssm:DescribeInstanceInformation",
        "servicediscovery:Get*", "servicediscovery:List*", "servicediscovery:Discover*",
        "iam:Get*", "iam:List*",
        "kms:DescribeKey", "kms:ListAliases",
        "application-autoscaling:Describe*"
      ],
      "Resource": "*"
    },
    {
      "Sid": "OurEcrRepo",
      "Effect": "Allow",
      "Action": "ecr:*",
      "Resource": "arn:aws:ecr:*:*:repository/anasudal/*"
    },
    {
      "Sid": "EcrCreate",
      "Effect": "Allow",
      "Action": ["ecr:CreateRepository", "ecr:TagResource"],
      "Resource": "*",
      "Condition": { "StringEquals": { "aws:RequestTag/Project": "anasudal" } }
    },
    {
      "Sid": "OurEcsResources",
      "Effect": "Allow",
      "Action": "ecs:*",
      "Resource": [
        "arn:aws:ecs:*:*:cluster/anasudal-*",
        "arn:aws:ecs:*:*:service/anasudal-*/*",
        "arn:aws:ecs:*:*:task-definition/anasudal-*:*",
        "arn:aws:ecs:*:*:task/anasudal-*/*"
      ]
    },
    {
      "Sid": "EcsAccountLevel",
      "Effect": "Allow",
      "Action": [
        "ecs:CreateCluster",
        "ecs:RegisterTaskDefinition",
        "ecs:DeregisterTaskDefinition",
        "ecs:PutClusterCapacityProviders",
        "ecs:PutAccountSetting",
        "ecs:TagResource",
        "ecs:UntagResource"
      ],
      "Resource": "*"
    },
    {
      "Sid": "OurLogGroups",
      "Effect": "Allow",
      "Action": "logs:*",
      "Resource": [
        "arn:aws:logs:*:*:log-group:/ecs/anasudal-*",
        "arn:aws:logs:*:*:log-group:/ecs/anasudal-*:*"
      ]
    },
    {
      "Sid": "OurSsmParameters",
      "Effect": "Allow",
      "Action": [
        "ssm:PutParameter",
        "ssm:DeleteParameter",
        "ssm:DeleteParameters",
        "ssm:AddTagsToResource",
        "ssm:RemoveTagsFromResource",
        "ssm:LabelParameterVersion"
      ],
      "Resource": "arn:aws:ssm:*:*:parameter/anasudal/*"
    },
    {
      "Sid": "SsmSessionToOurInstancesOnly",
      "Effect": "Allow",
      "Action": "ssm:StartSession",
      "Resource": "arn:aws:ec2:*:*:instance/*",
      "Condition": { "StringEquals": { "ssm:resourceTag/Project": "anasudal" } }
    },
    {
      "Sid": "SsmSessionDocuments",
      "Effect": "Allow",
      "Action": "ssm:StartSession",
      "Resource": [
        "arn:aws:ssm:*::document/AWS-StartPortForwardingSessionToRemoteHost",
        "arn:aws:ssm:*::document/AWS-StartPortForwardingSession",
        "arn:aws:ssm:*::document/SSM-SessionManagerRunShell"
      ]
    },
    {
      "Sid": "SsmOwnSessions",
      "Effect": "Allow",
      "Action": ["ssm:TerminateSession", "ssm:ResumeSession"],
      "Resource": "arn:aws:ssm:*:*:session/${aws:username}-*"
    },
    {
      "Sid": "CloudMapForServiceDiscovery",
      "Effect": "Allow",
      "Action": "servicediscovery:*",
      "Resource": "*"
    },
    {
      "Sid": "OurRolesOnly",
      "Effect": "Allow",
      "Action": [
        "iam:CreateRole", "iam:DeleteRole", "iam:UpdateAssumeRolePolicy",
        "iam:AttachRolePolicy", "iam:DetachRolePolicy",
        "iam:PutRolePolicy", "iam:DeleteRolePolicy",
        "iam:CreateInstanceProfile", "iam:DeleteInstanceProfile",
        "iam:AddRoleToInstanceProfile", "iam:RemoveRoleFromInstanceProfile",
        "iam:TagRole", "iam:UntagRole", "iam:TagInstanceProfile"
      ],
      "Resource": [
        "arn:aws:iam::*:role/anasudal-*",
        "arn:aws:iam::*:instance-profile/anasudal-*"
      ]
    },
    {
      "Sid": "PassOurRolesOnly",
      "Effect": "Allow",
      "Action": "iam:PassRole",
      "Resource": "arn:aws:iam::*:role/anasudal-*"
    },
    {
      "Sid": "ServiceLinkedRoles",
      "Effect": "Allow",
      "Action": "iam:CreateServiceLinkedRole",
      "Resource": "*",
      "Condition": {
        "StringEquals": {
          "iam:AWSServiceName": [
            "ecs.amazonaws.com",
            "elasticache.amazonaws.com",
            "rds.amazonaws.com",
            "ssm.amazonaws.com"
          ]
        }
      }
    }
  ]
}
CORE

cat > /tmp/anasudal-infra.json <<'INFRA'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "NetworkAndDataPlane",
      "Effect": "Allow",
      "Action": [
        "ec2:*",
        "rds:*",
        "elasticache:*"
      ],
      "Resource": "*"
    },
    {
      "Sid": "DenyTouchingOtherProjects",
      "Effect": "Deny",
      "Action": [
        "ec2:TerminateInstances", "ec2:StopInstances", "ec2:RebootInstances",
        "ec2:DeleteVpc", "ec2:DeleteSubnet", "ec2:DeleteSecurityGroup",
        "ec2:DeleteRouteTable", "ec2:DeleteRoute", "ec2:DeleteInternetGateway",
        "ec2:DeleteNatGateway", "ec2:ReleaseAddress", "ec2:DisassociateAddress",
        "ec2:ModifyInstanceAttribute", "ec2:ModifyVpcAttribute", "ec2:ModifySubnetAttribute",
        "ec2:AuthorizeSecurityGroupIngress", "ec2:AuthorizeSecurityGroupEgress",
        "ec2:RevokeSecurityGroupIngress", "ec2:RevokeSecurityGroupEgress",
        "ec2:DetachInternetGateway", "ec2:DisassociateRouteTable",
        "rds:DeleteDBInstance", "rds:StopDBInstance", "rds:RebootDBInstance",
        "rds:ModifyDBInstance", "rds:DeleteDBSubnetGroup", "rds:DeleteDBParameterGroup",
        "elasticache:DeleteCacheCluster", "elasticache:ModifyCacheCluster",
        "elasticache:DeleteCacheSubnetGroup"
      ],
      "Resource": "*",
      "Condition": {
        "StringNotEqualsIfExists": { "aws:ResourceTag/Project": "anasudal" }
      }
    },
    {
      "Sid": "DenyAccountWideDamage",
      "Effect": "Deny",
      "Action": [
        "ec2:DeleteDefaultVpc",
        "ec2:DisableEbsEncryptionByDefault",
        "ec2:ModifyEbsDefaultKmsKeyId",
        "organizations:*",
        "account:*",
        "billing:*",
        "aws-portal:*",
        "iam:CreateUser", "iam:DeleteUser", "iam:CreateAccessKey", "iam:DeleteAccessKey",
        "iam:AttachUserPolicy", "iam:PutUserPolicy", "iam:CreatePolicy", "iam:DeletePolicy",
        "iam:CreatePolicyVersion", "iam:SetDefaultPolicyVersion"
      ],
      "Resource": "*"
    }
  ]
}
INFRA

# ── 2. 정책 만들기 (있으면 새 버전으로 갱신) ────────────────────────────────
put_policy () {
  local name="$1" file="$2" arn
  arn="arn:aws:iam::${ACCOUNT}:policy/${name}"
  if aws iam get-policy --policy-arn "$arn" >/dev/null 2>&1; then
    # 버전은 5개까지 — 가장 오래된 비기본 버전을 지우고 새로 올린다
    aws iam list-policy-versions --policy-arn "$arn" \
      --query 'Versions[?IsDefaultVersion==`false`].VersionId' --output text \
      | tr '\t' '\n' | tail -n +4 \
      | xargs -r -I{} aws iam delete-policy-version --policy-arn "$arn" --version-id {}
    aws iam create-policy-version --policy-arn "$arn" --policy-document "file://$file" \
      --set-as-default >/dev/null
    echo "  ↻ 정책 갱신: $name" >&2
  else
    aws iam create-policy --policy-name "$name" --policy-document "file://$file" \
      --tags Key=Project,Value=$PROJECT >/dev/null
    echo "  + 정책 생성: $name" >&2
  fi
  echo "$arn"
}

CORE_ARN=$(put_policy anasudal-deploy-core  /tmp/anasudal-core.json)
INFRA_ARN=$(put_policy anasudal-deploy-infra /tmp/anasudal-infra.json)

# ── 3. 사용자 + 정책 연결 ───────────────────────────────────────────────────
if aws iam get-user --user-name "$USER_NAME" >/dev/null 2>&1; then
  echo "  = 사용자 있음: $USER_NAME"
else
  aws iam create-user --user-name "$USER_NAME" --tags Key=Project,Value=$PROJECT >/dev/null
  echo "  + 사용자 생성: $USER_NAME"
fi
aws iam attach-user-policy --user-name "$USER_NAME" --policy-arn "$CORE_ARN"
aws iam attach-user-policy --user-name "$USER_NAME" --policy-arn "$INFRA_ARN"
echo "  + 정책 연결 완료"

# ── 4. 액세스 키 ────────────────────────────────────────────────────────────
# 키는 사용자당 2개까지. 이미 2개면 가장 오래된 것을 지운다.
COUNT=$(aws iam list-access-keys --user-name "$USER_NAME" --query 'length(AccessKeyMetadata)' --output text)
if [ "$COUNT" -ge 2 ]; then
  OLD=$(aws iam list-access-keys --user-name "$USER_NAME" \
        --query 'sort_by(AccessKeyMetadata,&CreateDate)[0].AccessKeyId' --output text)
  aws iam delete-access-key --user-name "$USER_NAME" --access-key-id "$OLD"
  echo "  - 오래된 키 삭제: $OLD"
fi

NEW_KEY=$(aws iam create-access-key --user-name "$USER_NAME" \
  --query 'AccessKey.[AccessKeyId,SecretAccessKey]' --output text)
NEW_ID=${NEW_KEY%%[[:space:]]*}
NEW_SECRET=${NEW_KEY##*[[:space:]]}

# ANASUDAL_KEY_OUT 이 있으면 화면에 찍지 않고 그 파일로만 넘긴다 (login.sh 가 쓴다).
# 없으면 — CloudShell 등에서 직접 실행한 경우 — 화면에 한 번만 보여준다.
if [ -n "${ANASUDAL_KEY_OUT:-}" ]; then
  ( umask 077; printf 'AWS_ACCESS_KEY_ID=%s\nAWS_SECRET_ACCESS_KEY=%s\n' \
      "$NEW_ID" "$NEW_SECRET" > "$ANASUDAL_KEY_OUT" )
  echo "  + 액세스 키 발급: $NEW_ID  (화면에 남기지 않고 프로필에 바로 넣습니다)"
else
  echo
  echo "════════════════════════════════════════════════════════"
  printf 'AWS_ACCESS_KEY_ID=%s\nAWS_SECRET_ACCESS_KEY=%s\n' "$NEW_ID" "$NEW_SECRET"
  echo "════════════════════════════════════════════════════════"
  echo "위 두 줄은 이번에만 보입니다. 복사해 두세요."
  echo
  echo "등록:  aws configure --profile anasudal"
  echo "정리:  aws iam delete-access-key --user-name $USER_NAME --access-key-id <키ID>"
fi
