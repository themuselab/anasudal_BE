# ── ECS on EC2 ──────────────────────────────────────────────────────────────
#
# Fargate 대신 EC2 시작 유형을 쓴다. 게이트웨이 인스턴스가 곧 컨테이너 인스턴스다.
#   · Fargate 요금(월 ~$4)이 사라지고, 무엇보다 NAT Gateway(월 ~$43)가 필요 없어진다
#     (Fargate 태스크는 프라이빗 서브넷에 있어 ECR·Gemini 로 나가려면 NAT 가 필요했다)
#   · network_mode = "host" 라 Cloud Map 내부 DNS 도 필요 없다. nginx 가 127.0.0.1:8000
#     으로 바로 프록시하고, Postgres·Redis 도 같은 localhost 에서 보인다
#
# 인스턴스가 한 대이므로 배포는 기존 태스크를 내리고 새 태스크를 올리는 방식이다
# (min 0% / max 100%). 교체 중 수 초간 502 가 날 수 있다 — 해커톤에서는 감수한다.

resource "aws_cloudwatch_log_group" "api" {
  name              = "/ecs/${local.name}/api"
  retention_in_days = 7 # 비용. 기본 14일에서 줄임
}

resource "aws_ecs_cluster" "main" {
  name = local.name
  setting {
    name  = "containerInsights"
    value = "disabled" # 비용. 필요 시 enabled
  }
}

resource "aws_ecs_task_definition" "api" {
  family                   = "${local.name}-api"
  requires_compatibilities = ["EC2"]
  network_mode             = "host"
  execution_role_arn       = aws_iam_role.task_exec.arn
  task_role_arn            = aws_iam_role.task.arn

  container_definitions = jsonencode([{
    name      = "api"
    image     = "${aws_ecr_repository.api.repository_url}:${var.api_image_tag}"
    essential = true
    # host 모드에서는 containerPort 와 hostPort 가 같아야 한다
    portMappings = [{ containerPort = 8000, hostPort = 8000, protocol = "tcp" }]

    # 인스턴스 메모리(t3.small = 2GB)를 Postgres·Redis·nginx 와 나눠 쓴다.
    # 하드 리밋이라 넘으면 컨테이너가 죽는다 — 여유를 두고 잡는다.
    cpu               = var.api_cpu
    memory            = var.api_memory
    memoryReservation = floor(var.api_memory / 2)

    environment = [
      { name = "GEMINI_EMBED_MODEL", value = "models/gemini-embedding-2" },
      { name = "GEMINI_GEN_MODEL", value = "models/gemini-3.6-flash" },
      { name = "EMBED_DIM", value = "768" },
      { name = "SESSION_TTL_HOURS", value = "24" },
    ]
    secrets = [
      { name = "DATABASE_URL", valueFrom = aws_ssm_parameter.database_url.arn },
      { name = "GEMINI_API_KEYS", valueFrom = aws_ssm_parameter.gemini_api_keys.arn },
      { name = "GEMINI_SUMMARY_KEY", valueFrom = aws_ssm_parameter.gemini_summary_key.arn },
      { name = "CORS_ORIGINS", valueFrom = aws_ssm_parameter.cors_origins.arn },
      { name = "TOP_K", valueFrom = aws_ssm_parameter.top_k.arn },
      { name = "REDIS_URL", valueFrom = aws_ssm_parameter.redis_url.arn },
    ]
    healthCheck = {
      command     = ["CMD-SHELL", "curl -fsS http://127.0.0.1:8000/health || exit 1"]
      interval    = 30
      timeout     = 5
      retries     = 3
      startPeriod = 30
    }
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.api.name
        awslogs-region        = var.region
        awslogs-stream-prefix = "api"
      }
    }
  }])
}

resource "aws_ecs_service" "api" {
  name            = "api"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = var.api_desired_count
  launch_type     = "EC2"
  propagate_tags  = "SERVICE"

  # 컨테이너 인스턴스가 한 대라 새 태스크를 띄울 여유 포트가 없다.
  # 기존 것을 먼저 내리고 새로 올린다.
  deployment_minimum_healthy_percent = 0
  deployment_maximum_percent         = 100

  # 첫 배포 때 ECR 이 비어 있어 태스크가 못 뜨는데, 서킷 브레이커가 있으면
  # 되돌릴 이전 버전이 없어 배포가 실패로 고정된다. 그래서 켜지 않는다.

  # CI 가 새 리비전을 등록·배포하므로 이후 변경은 Terraform 이 무시한다
  lifecycle {
    ignore_changes = [task_definition, desired_count]
  }

  depends_on = [aws_instance.gateway]
}
