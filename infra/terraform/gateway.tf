# ── 외부 게이트웨이 EC2: nginx 리버스 프록시 + SSM 배스천. 22번 포트 없음 ───
data "aws_ami" "al2023_arm" {
  most_recent = true
  owners      = ["amazon"]
  filter {
    name   = "name"
    values = ["al2023-ami-2023.*-arm64"]
  }
}

resource "aws_eip" "gateway" {
  domain = "vpc"
  tags   = { Name = "${local.name}-gateway" }
}

resource "aws_instance" "gateway" {
  ami                         = data.aws_ami.al2023_arm.id
  instance_type               = var.gateway_instance_type
  subnet_id                   = aws_subnet.public[0].id
  vpc_security_group_ids      = [aws_security_group.gateway.id]
  iam_instance_profile        = aws_iam_instance_profile.gateway.name
  associate_public_ip_address = true
  key_name                    = null            # SSH 키 없음 — 접속은 SSM Session Manager

  metadata_options {
    http_tokens = "required"                    # IMDSv2 강제
  }
  root_block_device {
    volume_size = 8
    volume_type = "gp3"
    encrypted   = true
  }

  user_data = templatefile("${path.module}/templates/gateway-user-data.sh", {
    ssm_prefix = local.ssm_prefix
    region     = var.region
  })
  user_data_replace_on_change = true

  tags = { Name = "${local.name}-gateway", Role = "gateway" }
}

resource "aws_eip_association" "gateway" {
  instance_id   = aws_instance.gateway.id
  allocation_id = aws_eip.gateway.id
}
