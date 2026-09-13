# ── 게이트웨이 EC2: 이 프로젝트의 전부가 이 한 대에서 돈다 ─────────────────
#
#   nginx (호스트)        :80  → 127.0.0.1:8000
#   API   (ECS 태스크)    :8000
#   Postgres + pgvector   :5432  (127.0.0.1 에만 바인딩)
#   Redis                 :6379  (127.0.0.1 에만 바인딩)
#
# SSH 포트도 키페어도 없다. 관리 접속은 SSM Session Manager 뿐이다.

# ECS 최적화 AMI. 도커와 ECS 에이전트가 이미 들어 있다.
# x86_64 를 쓰는 이유: API 이미지가 GitHub Actions(ubuntu-latest, amd64)에서
# 평범한 docker build 로 만들어진다. ARM(t4g)으로 가려면 멀티아치 빌드가 필요한데
# 월 $3 차이라 그럴 값어치가 없다.
data "aws_ssm_parameter" "ecs_ami" {
  name = "/aws/service/ecs/optimized-ami/amazon-linux-2023/recommended/image_id"
}

resource "aws_eip" "gateway" {
  domain = "vpc"
  tags   = { Name = "${local.name}-gateway" }
}

resource "aws_instance" "gateway" {
  ami                         = data.aws_ssm_parameter.ecs_ami.value
  instance_type               = var.gateway_instance_type
  subnet_id                   = aws_subnet.public[0].id
  vpc_security_group_ids      = [aws_security_group.gateway.id]
  iam_instance_profile        = aws_iam_instance_profile.gateway.name
  associate_public_ip_address = true
  key_name                    = null # SSH 키 없음

  metadata_options {
    http_tokens = "required" # IMDSv2 강제
  }

  root_block_device {
    # DB 데이터가 여기 산다(/var/lib/anasudal). 컨테이너 이미지도 쌓이므로 넉넉히.
    volume_size           = var.data_volume_gb
    volume_type           = "gp3"
    encrypted             = true
    delete_on_termination = true
  }

  user_data = templatefile("${path.module}/templates/gateway-user-data.sh", {
    cluster_name = local.name
    ssm_prefix   = local.ssm_prefix
    region       = var.region
    db_username  = var.db_username
    db_name      = var.db_name
  })

  # user_data 를 바꾸면 인스턴스를 새로 만든다.
  # 주의: 그러면 EBS 루트 볼륨과 함께 DB 데이터도 사라진다. 지식베이스는
  #      db-init.sh 로 다시 적재할 수 있지만, 세션 기록은 복구되지 않는다.
  user_data_replace_on_change = true

  tags = { Name = "${local.name}-gateway", Role = "gateway" }
}

resource "aws_eip_association" "gateway" {
  instance_id   = aws_instance.gateway.id
  allocation_id = aws_eip.gateway.id
}
