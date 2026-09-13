output "gateway_public_ip" {
  value       = aws_eip.gateway.public_ip
  description = "API 진입점: http://<ip>/v1/..."
}

output "gateway_instance_id" {
  value       = aws_instance.gateway.id
  description = "SSM Session Manager 대상"
}

output "ecr_repository_url" { value = aws_ecr_repository.api.repository_url }
output "ecs_cluster"        { value = aws_ecs_cluster.main.name }
output "ecs_service"        { value = aws_ecs_service.api.name }
output "task_family"        { value = aws_ecs_task_definition.api.family }

output "rds_endpoint" {
  value       = aws_db_instance.db.address
  description = "프라이빗. SSM 포트포워딩으로만 접근"
}

output "ssm_database_url_param" { value = aws_ssm_parameter.database_url.name }
output "api_internal_host"      { value = aws_ssm_parameter.api_internal_host.value }

output "gha_deploy_role_arn" {
  value = var.github_repo != "" ? aws_iam_role.gha_deploy[0].arn : null
}

output "region" { value = var.region }

output "redis_endpoint" { value = aws_elasticache_cluster.redis.cache_nodes[0].address }
