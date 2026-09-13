# ── Cloud Map: 게이트웨이 nginx가 태스크를 찾는 내부 DNS (ALB 없이) ─────────
resource "aws_service_discovery_private_dns_namespace" "ns" {
  name = "${var.project}.local"
  vpc  = aws_vpc.main.id
}

resource "aws_service_discovery_service" "api" {
  name = "api"
  dns_config {
    namespace_id   = aws_service_discovery_private_dns_namespace.ns.id
    routing_policy = "MULTIVALUE"
    dns_records {
      type = "A"
      ttl  = 10
    }
  }
  health_check_custom_config { failure_threshold = 1 }
}

# ── ECS Fargate ─────────────────────────────────────────────────────────────
resource "aws_cloudwatch_log_group" "api" {
  name              = "/ecs/${local.name}/api"
  retention_in_days = 14
}

resource "aws_ecs_cluster" "main" {
  name = local.name
  setting {
    name  = "containerInsights"
    value = "disabled"     # 비용. 필요 시 enabled
  }
}

resource "aws_ecs_cluster_capacity_providers" "main" {
  cluster_name       = aws_ecs_cluster.main.name
  capacity_providers = ["FARGATE", "FARGATE_SPOT"]
  default_capacity_provider_strategy {
    capacity_provider = "FARGATE_SPOT"    # 해커톤: 스팟으로 ~70% 절감. 운영 전환 시 FARGATE
    weight            = 1
  }
}

resource "aws_ecs_task_definition" "api" {
  family                   = "${local.name}-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.api_cpu
  memory                   = var.api_memory
  execution_role_arn       = aws_iam_role.task_exec.arn
  task_role_arn            = aws_iam_role.task.arn
  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([{
    name      = "api"
    image     = "${aws_ecr_repository.api.repository_url}:${var.api_image_tag}"
    essential = true
    portMappings = [{ containerPort = 8000, protocol = "tcp" }]
    environment = [
      { name = "GEMINI_EMBED_MODEL", value = "models/gemini-embedding-2" },
      { name = "GEMINI_GEN_MODEL",   value = "models/gemini-3.6-flash" },
      { name = "EMBED_DIM",          value = "768" },
      { name = "SESSION_TTL_HOURS",  value = "24" },
    ]
    secrets = [
      { name = "DATABASE_URL",   valueFrom = aws_ssm_parameter.database_url.arn },
      { name = "GEMINI_API_KEY", valueFrom = aws_ssm_parameter.gemini_api_key.arn },
      { name = "CORS_ORIGINS",   valueFrom = aws_ssm_parameter.cors_origins.arn },
      { name = "TOP_K",          valueFrom = aws_ssm_parameter.top_k.arn },
      { name = "REDIS_URL",      valueFrom = aws_ssm_parameter.redis_url.arn },
    ]
    healthCheck = {
      command     = ["CMD-SHELL", "curl -fsS http://127.0.0.1:8000/health || exit 1"]
      interval    = 30
      timeout     = 5
      retries     = 3
      startPeriod = 20
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
  propagate_tags  = "SERVICE"

  capacity_provider_strategy {
    capacity_provider = "FARGATE_SPOT"
    weight            = 1
  }

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.api.id]
    assign_public_ip = false
  }

  service_registries {
    registry_arn = aws_service_discovery_service.api.arn
  }

  deployment_minimum_healthy_percent = 50
  deployment_maximum_percent         = 200
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  # CI가 새 태스크 리비전을 등록·배포하므로 Terraform은 이후 변경을 무시
  lifecycle {
    ignore_changes = [task_definition, desired_count]
  }

  depends_on = [aws_nat_gateway.nat]
}
