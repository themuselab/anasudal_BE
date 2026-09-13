# ── VPC: 퍼블릭 서브넷만. NAT Gateway 없음 ─────────────────────────────────
#
# 모든 것이 게이트웨이 EC2 한 대 위에서 돈다(nginx·API·Postgres·Redis).
# 그 인스턴스가 퍼블릭 서브넷에 있고 EIP 로 직접 나가므로 NAT(월 ~$43)가 필요 없다.
# 서브넷을 2개 두는 것은 ECS 가 AZ 선택지를 갖게 하기 위한 것이고 추가 비용은 없다.
resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags                 = { Name = local.name }
}

resource "aws_internet_gateway" "igw" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = "${local.name}-igw" }
}

resource "aws_subnet" "public" {
  count                   = 2
  vpc_id                  = aws_vpc.main.id
  cidr_block              = cidrsubnet(var.vpc_cidr, 8, count.index) # 10.20.0.0/24, 10.20.1.0/24
  availability_zone       = local.azs[count.index]
  map_public_ip_on_launch = true
  tags                    = { Name = "${local.name}-public-${count.index}", Tier = "public" }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.igw.id
  }
  tags = { Name = "${local.name}-rt-public" }
}

resource "aws_route_table_association" "public" {
  count          = 2
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

# ── 보안 그룹 ───────────────────────────────────────────────────────────────
# 외부에 여는 것은 80/443 뿐이다. SSH(22) 없음 — 관리 접속은 SSM Session Manager.
# Postgres(5432)·Redis(6379)·API(8000) 는 127.0.0.1 에만 바인딩되므로
# 보안 그룹에 규칙이 없어도 인스턴스 내부에서만 닿는다.
resource "aws_security_group" "gateway" {
  name        = "${local.name}-gateway"
  description = "Public entry: HTTP/HTTPS only. Admin via SSM Session Manager."
  vpc_id      = aws_vpc.main.id

  ingress {
    description = "HTTP"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = var.gateway_ingress_cidrs
  }
  ingress {
    description = "HTTPS"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = var.gateway_ingress_cidrs
  }
  egress {
    description = "ECR pull, Gemini API, SSM"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${local.name}-gateway" }
}
