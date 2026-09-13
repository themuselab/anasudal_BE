# ── ECS 태스크 실행 역할: ECR pull · CloudWatch logs · SSM 파라미터 복호화 ─
data "aws_iam_policy_document" "ecs_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "task_exec" {
  name               = "${local.name}-task-exec"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy_attachment" "task_exec_managed" {
  role       = aws_iam_role.task_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

data "aws_kms_alias" "ssm" { name = "alias/aws/ssm" }

data "aws_iam_policy_document" "task_exec_ssm" {
  statement {
    actions   = ["ssm:GetParameters", "ssm:GetParameter"]
    resources = ["arn:aws:ssm:${var.region}:${data.aws_caller_identity.me.account_id}:parameter${local.ssm_prefix}/*"]
  }
  statement {
    actions   = ["kms:Decrypt"]
    resources = [data.aws_kms_alias.ssm.target_key_arn]   # 별칭 ARN은 IAM에서 안 먹힘 → 실제 키 ARN
  }
}

resource "aws_iam_role_policy" "task_exec_ssm" {
  name   = "ssm-parameters"
  role   = aws_iam_role.task_exec.id
  policy = data.aws_iam_policy_document.task_exec_ssm.json
}

# 태스크 역할(앱 런타임 권한). 지금은 AWS API를 직접 안 쓰므로 비어 있음
resource "aws_iam_role" "task" {
  name               = "${local.name}-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

# ── 게이트웨이 EC2 인스턴스 역할: SSM Session Manager + 파라미터 읽기 ───────
data "aws_iam_policy_document" "ec2_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "gateway" {
  name               = "${local.name}-gateway"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume.json
}

resource "aws_iam_role_policy_attachment" "gateway_ssm" {
  role       = aws_iam_role.gateway.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_role_policy" "gateway_params" {
  name   = "read-app-params"
  role   = aws_iam_role.gateway.id
  policy = data.aws_iam_policy_document.task_exec_ssm.json
}

resource "aws_iam_instance_profile" "gateway" {
  name = "${local.name}-gateway"
  role = aws_iam_role.gateway.name
}

# ── GitHub Actions OIDC 배포 역할 (github_repo 지정 시) ────────────────────
data "aws_iam_openid_connect_provider" "github" {
  count = var.github_repo != "" ? 1 : 0
  url   = "https://token.actions.githubusercontent.com"
}

data "aws_iam_policy_document" "gha_assume" {
  count = var.github_repo != "" ? 1 : 0
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [data.aws_iam_openid_connect_provider.github[0].arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repo}:*"]
    }
  }
}

resource "aws_iam_role" "gha_deploy" {
  count              = var.github_repo != "" ? 1 : 0
  name               = "${local.name}-gha-deploy"
  assume_role_policy = data.aws_iam_policy_document.gha_assume[0].json
}

data "aws_iam_policy_document" "gha_deploy" {
  count = var.github_repo != "" ? 1 : 0
  statement {
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }
  statement {
    actions = ["ecr:BatchCheckLayerAvailability", "ecr:CompleteLayerUpload", "ecr:InitiateLayerUpload",
               "ecr:PutImage", "ecr:UploadLayerPart", "ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"]
    resources = [aws_ecr_repository.api.arn]
  }
  statement {
    actions   = ["ecs:DescribeTaskDefinition", "ecs:RegisterTaskDefinition", "ecs:DescribeServices", "ecs:UpdateService"]
    resources = ["*"]
  }
  statement {
    actions   = ["iam:PassRole"]
    resources = [aws_iam_role.task_exec.arn, aws_iam_role.task.arn]
  }
}

resource "aws_iam_role_policy" "gha_deploy" {
  count  = var.github_repo != "" ? 1 : 0
  name   = "deploy"
  role   = aws_iam_role.gha_deploy[0].id
  policy = data.aws_iam_policy_document.gha_deploy[0].json
}
