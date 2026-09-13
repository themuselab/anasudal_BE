# 안아수달 AWS 인프라 — ECS/ECR + SSM 게이트웨이 EC2

```
                    인터넷
                      │  :80 / :443
        ┌─────────────▼──────────────┐   퍼블릭 서브넷 (10.20.0.0/24, 10.20.1.0/24)
        │  게이트웨이 EC2 (t4g.micro)  │   · nginx 리버스 프록시 → api.anasudal.local:8000
        │  AL2023 · SSM Agent · EIP    │   · SSH 없음(22 미개방). 운영 접속 = SSM Session Manager
        │  IAM: SSMManagedInstanceCore │   · RDS 접근 통로 (SSM 포트포워딩)
        └─────────────┬──────────────┘
                      │ 8000 (SG: gateway → api 만)
        ┌─────────────▼──────────────┐   프라이빗 서브넷 (10.20.10.0/24, 10.20.11.0/24)
        │  ECS Fargate(Spot) 서비스    │   · 이미지: ECR anasudal/api
        │  FastAPI ×N · Cloud Map DNS  │   · 비밀: SSM Parameter Store(SecureString) → 컨테이너 env
        └──────┬──────────────┬──────┘   · 외부(Gemini API) 호출은 NAT GW 경유
               │ 5432          │ 6379   (SG: api·gateway 만)
   ┌───────────▼──────────┐ ┌──▼───────────────────┐
   │ RDS PostgreSQL 16     │ │ ElastiCache Redis 7   │  캐시·임베딩 캐시·칩 회전·
   │ + pgvector, 비공개     │ │ cache.t4g.micro ×1    │  레이트리밋·답변 임시보관
   └──────────────────────┘ └──────────────────────┘
```

## 왜 이 구성인가

| 결정 | 이유 |
|---|---|
| **ALB 대신 EC2 nginx 게이트웨이** | 요구사항(외부 게이트웨이 = EC2). ALB 고정비(~$20/월)도 절감. Cloud Map 내부 DNS로 태스크 IP 변경을 흡수 |
| **SSM으로만 접속** | 22번 포트·키페어 없음. IAM 권한만으로 셸/포트포워딩. 감사 로그가 CloudTrail에 남음 |
| **Fargate Spot** | 해커톤 기간 비용 ~70% 절감. 운영 전환 시 `capacity_provider = "FARGATE"` 한 줄 |
| **SSM Parameter Store** | Secrets Manager($0.4/비밀/월) 대신 무료. 태스크 정의 `secrets`로 주입돼 이미지·코드에 키 없음 |
| **NAT 단일 AZ** | Gemini 호출용 출구. 이중화 시 AZ당 $32/월 추가 → MVP엔 과함 |
| **Terraform lifecycle ignore** | 태스크 정의는 CI가 리비전 갱신. Terraform은 인프라만 관리 |

## 파일

```
backend/Dockerfile                 python:3.11-slim, uvicorn 2 workers, non-root, HEALTHCHECK /health
infra/terraform/
  versions.tf   provider·backend(S3, 주석)   vpc.tf      VPC·서브넷·NAT·보안그룹 3개
  rds.tf        PG16 + 비밀번호 랜덤          ssm.tf      파라미터 5개(DSN, Gemini 키, CORS, TOP_K, 내부호스트)
  ecr.tf        리포지토리 + 10개 보관         ecs.tf      Cloud Map·클러스터·태스크정의·서비스
  elasticache.tf Redis 7 단일 노드 + SG + REDIS_URL 파라미터
  iam.tf        태스크실행/태스크/게이트웨이/GitHub OIDC 역할
  gateway.tf    EC2 + EIP + user-data(nginx)  outputs.tf  진입 IP, 인스턴스 ID, ECR URL 등
  templates/gateway-user-data.sh    nginx 설정 생성 (resolver = VPC DNS, 10초 재해석)
infra/scripts/
  first-push.sh   첫 이미지 ECR 푸시 + 강제 재배포      db-tunnel.sh   localhost:15432 → RDS (SSM)
  db-init.sh      터널 통해 01_schema + 02_load 실행     shell.sh       게이트웨이 SSM 셸
.github/workflows/deploy.yml   main push → build → ECR → 태스크정의 렌더 → ECS 롤링 배포
```

## 배포 순서

```bash
# 0. 사전 준비 (1회)
#    - AWS CLI 로그인, Session Manager 플러그인 설치
#    - GitHub OIDC 공급자 (계정당 1회):
#      aws iam create-open-id-connect-provider --url https://token.actions.githubusercontent.com \
#        --client-id-list sts.amazonaws.com
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars   # gemini_api_key, github_repo, cors_origins 채우기
terraform init && terraform apply             # ~12분 (RDS가 대부분)

# 1. 첫 이미지 (ECR이 비어 있어 서비스가 아직 못 뜸)
../scripts/first-push.sh

# 2. DB 초기화 — 터미널 A에서 터널, 터미널 B에서 적재
../scripts/db-tunnel.sh
python ../../scripts/kb_to_csv.py && ../scripts/db-init.sh       # 2,866 기관 · 1,473 청크 · MV 4개

# 3. 확인
curl http://$(terraform output -raw gateway_public_ip)/health
curl http://$(terraform output -raw gateway_public_ip)/v1/regions/sido

# 4. 이후 배포: GitHub Secrets에 AWS_DEPLOY_ROLE_ARN = terraform output gha_deploy_role_arn
#    main에 backend/ 변경 push → 자동 배포
```

## 운영

| 작업 | 명령 |
|---|---|
| 게이트웨이 셸 | `infra/scripts/shell.sh` → `sudo tail -f /var/log/nginx/error.log` |
| API 로그 | CloudWatch `/ecs/anasudal-prod/api` |
| DB 접속 | `db-tunnel.sh` 후 `psql postgresql://anasudal:<pw>@localhost:15432/anasudal?sslmode=require` |
| MV 갱신 | `SELECT refresh_all_mvs();` (가격 공시 갱신 후) — 조회 캐시는 10분 뒤 자동 반영 |
| 학습 데이터 덤프 | 터널 후 `psql ... -c "\copy (SELECT row_to_json(v) FROM v_training_export v) TO 'train.jsonl'"` |
| 세션 정리 | `SELECT purge_expired_sessions();` — EventBridge 스케줄로 자동화 가능 |
| 스케일 | `aws ecs update-service --desired-count 2` (Terraform은 desired_count 무시) |
| 키 교체 | `aws ssm put-parameter --name /anasudal/prod/GEMINI_API_KEY --overwrite ...` 후 재배포 |

## 비용 (서울, 월 기준 추정)

| 항목 | 사양 | 월 |
|---|---|---|
| RDS | db.t4g.micro + gp3 20GB | ~$15 |
| Fargate Spot | 0.5 vCPU / 1 GB × 1 | ~$6 |
| 게이트웨이 EC2 | t4g.micro + EIP | ~$8 |
| ElastiCache Redis | cache.t4g.micro ×1 | ~$12 |
| NAT Gateway | 1 AZ + 소량 트래픽 | ~$33 |
| ECR / CloudWatch / SSM | | ~$2 |
| **합계** | | **~$76** |

NAT가 절반이다. 더 줄이려면 ECS 태스크를 퍼블릭 서브넷에 두고 `assign_public_ip = true`로 바꿔 NAT를 제거할 수 있으나, 태스크가 공인 IP를 갖게 되므로 보안그룹(8000은 게이트웨이만)이 유일한 방벽이 된다. MVP 기간엔 허용 가능한 절충.

## 아직 안 한 것

- **HTTPS**: 도메인이 정해지면 게이트웨이에 certbot(Let's Encrypt) 추가 — user-data 10줄. 심사용 IP 접속은 HTTP.
- **terraform validate 미실행**: 이 PC에 Terraform이 없어 HCL 파서(python-hcl2)로 문법·참조 무결성만 검사했다. `terraform init && terraform plan`으로 최종 확인 필요.
- **Docker 빌드 미검증**: Docker Desktop이 꺼져 있어 이미지 빌드는 못 돌렸다.
- **오토스케일**: 심사 트래픽 수준에선 불필요. 필요 시 `aws_appautoscaling_target` 추가.
