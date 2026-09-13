# ── 데이터 계층: Postgres(pgvector) · Redis 를 게이트웨이 EC2 안 컨테이너로 ──
#
# RDS(월 ~$19) + ElastiCache(월 ~$17) 대신 같은 인스턴스에서 컨테이너로 돌린다.
# 해커톤 검증용으로 비용을 최소화하기 위한 선택이며, 맞바꾼 것은 다음과 같다.
#
#   잃는 것 : 자동 백업·시점 복원, 자동 패치, 인스턴스 장애 시 DB 도 같이 내려감
#   남는 것 : 데이터는 EBS 루트 볼륨의 /var/lib/anasudal 에 있어 재부팅·컨테이너
#             교체·ECS 재배포에는 그대로 살아남는다. 지식베이스는 CSV 에서 다시
#             적재할 수 있다(scripts/kb_to_csv.py → db-init.sh).
#
# 운영으로 넘길 때는 이 파일을 지우고 rds.tf / elasticache.tf 를 되살리면 된다
# (git 이력에 있음). DATABASE_URL·REDIS_URL 만 바꾸면 앱은 그대로 동작한다.

resource "random_password" "db" {
  length  = 32
  special = false # DSN 에 그대로 넣기 위해 특수문자 제외
}

# user-data 가 부팅 시 여기서 비밀번호를 읽어 Postgres 컨테이너에 넣는다.
# user-data 에 직접 박으면 EC2 콘솔과 IMDS 로 평문이 노출되므로 그렇게 하지 않는다.
resource "aws_ssm_parameter" "db_password" {
  name  = "${local.ssm_prefix}/DB_PASSWORD"
  type  = "SecureString"
  value = random_password.db.result
}

locals {
  # API 태스크는 network_mode = "host" 라 인스턴스의 localhost 를 그대로 본다.
  database_url = "postgresql://${var.db_username}:${random_password.db.result}@127.0.0.1:5432/${var.db_name}"
  redis_url    = "redis://127.0.0.1:6379/0"
}
