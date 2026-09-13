# ── ElastiCache Redis 7 (프라이빗, 단일 노드) ────────────────────────────────
#  용도: 조회 캐시 · 질문 임베딩 캐시 · 칩 회전/레이트리밋 카운터. 날아가도 되는 데이터만.
resource "aws_security_group" "redis" {
  name        = "${local.name}-redis"
  description = "Redis: 6379 from API tasks and gateway"
  vpc_id      = aws_vpc.main.id

  ingress {
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    security_groups = [aws_security_group.api.id, aws_security_group.gateway.id]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_elasticache_subnet_group" "redis" {
  name       = "${local.name}-redis"
  subnet_ids = aws_subnet.private[*].id
}

resource "aws_elasticache_cluster" "redis" {
  cluster_id           = "${local.name}-redis"
  engine               = "redis"
  engine_version       = "7.1"
  node_type            = var.redis_node_type
  num_cache_nodes      = 1
  parameter_group_name = "default.redis7"
  port                 = 6379
  subnet_group_name    = aws_elasticache_subnet_group.redis.name
  security_group_ids   = [aws_security_group.redis.id]
  apply_immediately    = true
  tags                 = { Name = "${local.name}-redis" }
}

locals {
  redis_url = "redis://${aws_elasticache_cluster.redis.cache_nodes[0].address}:6379/0"
}

resource "aws_ssm_parameter" "redis_url" {
  name  = "${local.ssm_prefix}/REDIS_URL"
  type  = "String"
  value = local.redis_url
}
