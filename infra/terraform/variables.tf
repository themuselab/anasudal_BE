variable "project" { default = "anasudal" }
variable "env" { default = "prod" }
variable "region" { default = "ap-northeast-2" } # 서울

variable "vpc_cidr" { default = "10.20.0.0/16" }

# ── ECS
variable "api_cpu" { default = 512 }    # 0.5 vCPU
variable "api_memory" { default = 768 } # MiB
variable "api_desired_count" { default = 1 }
variable "api_image_tag" { default = "latest" } # CI가 새 리비전을 등록하므로 초기값만 의미 있음

# ── Postgres (게이트웨이 EC2 안 컨테이너)
variable "db_name" { default = "anasudal" }
variable "db_username" { default = "anasudal" }

# ── Gateway EC2
variable "gateway_instance_type" { default = "t3.small" }
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
# 근거를 몇 건 넘길까. 측정으로 정한 값이라 바꾸려면 회귀부터 —
# backend/docs/rag-tuning.md 15번. 코드 기본값(config.py)과 같이 움직여야 한다.
variable "top_k" { default = "4" }

# ── CI (GitHub Actions OIDC). 비우면 IAM 역할을 만들지 않음
variable "github_repo" {
  description = "org/repo 형식. 예: anasudal/anasudal"
  default     = ""
}

# GitHub 불변 주체(immutable subject) — 조직/저장소 ID 가 박힌 형태.
# 요즘 저장소는 OIDC 토큰의 sub 가 "repo:<org>@<orgId>/<repo>@<repoId>:..." 로 나온다.
# 값 확인:  gh api repos/<org>/<repo>/actions/oidc/customization/sub  → sub_claim_prefix
# 비워두면 예전 형식만 허용한다 (그 경우 배포가 AssumeRoleWithWebIdentity 에서 막힌다).
variable "github_repo_immutable" {
  description = "예: themuselab@273790255/anasudal_BE@1367982784"
  default     = ""
}

variable "create_github_oidc" {
  description = "GitHub Actions OIDC 공급자를 직접 만든다. 계정에 이미 있으면 false"
  type        = bool
  default     = true
}

variable "data_volume_gb" {
  description = "게이트웨이 루트 볼륨(GB). DB 데이터와 컨테이너 이미지가 여기 산다"
  type        = number
  default     = 30
}
