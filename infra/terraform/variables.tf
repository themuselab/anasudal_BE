variable "project" { default = "anasudal" }
variable "env"     { default = "prod" }
variable "region"  { default = "ap-northeast-2" }   # 서울

variable "vpc_cidr" { default = "10.20.0.0/16" }

# ── ECS
variable "api_cpu"           { default = 512 }    # 0.5 vCPU
variable "api_memory"        { default = 1024 }   # MiB
variable "api_desired_count" { default = 1 }
variable "api_image_tag"     { default = "latest" }   # CI가 새 리비전을 등록하므로 초기값만 의미 있음

# ── RDS
variable "db_instance_class"  { default = "db.t4g.micro" }
variable "db_engine_version"  { default = "16.4" }        # pgvector 지원
variable "db_allocated_gb"    { default = 20 }
variable "db_name"            { default = "anasudal" }
variable "db_username"        { default = "anasudal" }

# ── Redis
variable "redis_node_type" { default = "cache.t4g.micro" }

# ── Gateway EC2
variable "gateway_instance_type" { default = "t4g.micro" }
variable "gateway_ingress_cidrs" {
  description = "80/443 허용 대역. 해커톤 심사 기간엔 전체, 이후 좁힐 것"
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

# ── 앱 설정 (SSM Parameter Store로 들어감)
# 답변·임베딩용 키 (여러 개). 하나가 429 면 앱이 다음 키로 넘어간다
variable "gemini_api_keys" {
  type      = list(string)
  sensitive = true
}

# 질문 요약(백그라운드로 DB 에 쌓음) 전용 키. 답변 쿼터와 분리한다
variable "gemini_summary_key" {
  type      = string
  sensitive = true
}
variable "cors_origins" { default = "http://localhost:5173" }
variable "top_k"        { default = "3" }

# ── CI (GitHub Actions OIDC). 비우면 IAM 역할을 만들지 않음
variable "github_repo" {
  description = "org/repo 형식. 예: anasudal/anasudal"
  default     = ""
}
