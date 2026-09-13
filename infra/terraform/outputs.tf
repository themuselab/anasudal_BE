output "gateway_public_ip" {
  value       = aws_eip.gateway.public_ip
  description = "API 진입점: http://<ip>/v1/..."
}

output "gateway_instance_id" {
  value       = aws_instance.gateway.id
  description = "SSM Session Manager 대상. 셸·DB 터널 모두 이 인스턴스로."
}

output "ecr_repository_url" { value = aws_ecr_repository.api.repository_url }
output "ecs_cluster" { value = aws_ecs_cluster.main.name }
output "ecs_service" { value = aws_ecs_service.api.name }
output "task_family" { value = aws_ecs_task_definition.api.family }
output "region" { value = var.region }

output "ssm_database_url_param" {
  value       = aws_ssm_parameter.database_url.name
  description = "DB 접속 문자열이 든 SSM 파라미터 이름"
}

output "ssm_db_password_param" {
  value       = aws_ssm_parameter.db_password.name
  description = "DB 비밀번호. 값 보기: aws ssm get-parameter --name <이 값> --with-decryption"
}

output "gha_deploy_role_arn" {
  value       = var.github_repo != "" ? aws_iam_role.gha_deploy[0].arn : null
  description = "GitHub Secrets 의 AWS_DEPLOY_ROLE_ARN 에 넣을 값"
}

output "api_https_url" {
  value       = "https://${aws_cloudfront_distribution.api.domain_name}"
  description = "프론트(Vercel)에서 호출할 주소. HTTPS 종단은 CloudFront."
}

output "api_http_url" {
  value       = "http://${aws_eip.gateway.public_ip}"
  description = "게이트웨이 직통. 디버깅용 — 브라우저에서 쓰면 mixed content 로 막힌다."
}
