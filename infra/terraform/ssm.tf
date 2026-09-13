# ── SSM Parameter Store: 앱 설정. SecureString은 기본 KMS 키(aws/ssm) ──────
locals {
  ssm_prefix = "/${var.project}/${var.env}"
}

resource "aws_ssm_parameter" "database_url" {
  name  = "${local.ssm_prefix}/DATABASE_URL"
  type  = "SecureString"
  value = local.database_url
}

resource "aws_ssm_parameter" "gemini_api_key" {
  name  = "${local.ssm_prefix}/GEMINI_API_KEY"
  type  = "SecureString"
  value = var.gemini_api_key
}

resource "aws_ssm_parameter" "cors_origins" {
  name  = "${local.ssm_prefix}/CORS_ORIGINS"
  type  = "String"
  value = var.cors_origins
}

resource "aws_ssm_parameter" "top_k" {
  name  = "${local.ssm_prefix}/TOP_K"
  type  = "String"
  value = var.top_k
}

# 게이트웨이 EC2가 nginx 업스트림으로 쓸 내부 DNS 이름
resource "aws_ssm_parameter" "api_internal_host" {
  name  = "${local.ssm_prefix}/API_INTERNAL_HOST"
  type  = "String"
  value = "${aws_service_discovery_service.api.name}.${aws_service_discovery_private_dns_namespace.ns.name}"
}
