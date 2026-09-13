terraform {
  required_version = ">= 1.6"
  required_providers {
    aws    = { source = "hashicorp/aws", version = "~> 5.60" }
    random = { source = "hashicorp/random", version = "~> 3.6" }
  }
  # 팀 공유용 원격 상태 — 버킷은 먼저 만들어 두고 주석 해제
  # backend "s3" {
  #   bucket         = "anasudal-tfstate"
  #   key            = "prod/terraform.tfstate"
  #   region         = "ap-northeast-2"
  #   dynamodb_table = "anasudal-tflock"
  #   encrypt        = true
  # }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = { Project = var.project, Env = var.env, ManagedBy = "terraform" }
  }
}

data "aws_caller_identity" "me" {}
data "aws_availability_zones" "azs" { state = "available" }

locals {
  name = "${var.project}-${var.env}"
  azs  = slice(data.aws_availability_zones.azs.names, 0, 2)
}
