# ── RDS PostgreSQL 16 + pgvector (프라이빗 서브넷) ──────────────────────────
resource "random_password" "db" {
  length  = 32
  special = false     # DSN에 안전하게 넣기 위해 특수문자 제외
}

resource "aws_db_subnet_group" "db" {
  name       = "${local.name}-db"
  subnet_ids = aws_subnet.private[*].id
}

resource "aws_db_parameter_group" "pg16" {
  name   = "${local.name}-pg16"
  family = "postgres16"
  # pgvector는 확장(CREATE EXTENSION vector)만 하면 됨. rds.force_ssl 기본 1 → DSN에 sslmode=require
}

resource "aws_db_instance" "db" {
  identifier              = "${local.name}-db"
  engine                  = "postgres"
  engine_version          = var.db_engine_version
  instance_class          = var.db_instance_class
  allocated_storage       = var.db_allocated_gb
  storage_type            = "gp3"
  db_name                 = var.db_name
  username                = var.db_username
  password                = random_password.db.result
  db_subnet_group_name    = aws_db_subnet_group.db.name
  vpc_security_group_ids  = [aws_security_group.db.id]
  parameter_group_name    = aws_db_parameter_group.pg16.name
  publicly_accessible     = false
  multi_az                = false
  backup_retention_period = 3
  deletion_protection     = false           # 해커톤. 운영 전환 시 true
  skip_final_snapshot     = true
  apply_immediately       = true
  performance_insights_enabled = false
  tags = { Name = "${local.name}-db" }
}

locals {
  database_url = "postgresql://${var.db_username}:${random_password.db.result}@${aws_db_instance.db.address}:5432/${var.db_name}?sslmode=require"
}
