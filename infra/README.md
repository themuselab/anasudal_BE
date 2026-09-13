# 안아수달 AWS 아키텍처

같은 AWS 계정에 다른 프로젝트가 이미 있습니다. **네트워크·이름·권한 세 겹으로 분리**해서,
이 프로젝트가 기존 것을 건드릴 수 없고 기존 것도 이 프로젝트에 영향을 주지 않게 합니다.

---

## 전체 그림

```
                              인터넷
                                │ :80 / :443
   ┌────────────────────────────▼─────────────────────────────┐
   │  VPC  anasudal-prod   10.20.0.0/16   (기본 VPC 안 씀)      │
   │                                                           │
   │  퍼블릭 10.20.0.0/24 · 10.20.1.0/24                       │
   │   ┌──────────────────────────┐   ┌────────────────────┐  │
   │   │ 게이트웨이 EC2 t4g.micro  │   │ NAT GW (단일 AZ)    │  │
   │   │ · nginx → ECS 태스크      │   │ · 태스크의 외부 출구 │  │
   │   │ · SSM 배스천 (22번 없음)  │   │   (Gemini 호출)     │  │
   │   │ · EIP 고정                │   └────────┬───────────┘  │
   │   └────────────┬─────────────┘            │              │
   │        8000    │  (SG: 게이트웨이만)       │              │
   │  프라이빗 10.20.10.0/24 · 10.20.11.0/24    │              │
   │   ┌────────────▼─────────────────────────▼────────────┐  │
   │   │ ECS Fargate Spot  ·  anasudal-prod 클러스터        │  │
   │   │ FastAPI 태스크 ×N  ·  이미지: ECR anasudal/api     │  │
   │   │ 내부 DNS: api.anasudal.local (Cloud Map)           │  │
   │   │ 비밀: SSM Parameter Store → 컨테이너 env           │  │
   │   └───────┬───────────────────────────┬───────────────┘  │
   │    5432   │                    6379   │                  │
   │   ┌───────▼──────────┐      ┌─────────▼──────────┐       │
   │   │ RDS PostgreSQL 16│      │ ElastiCache Redis 7│       │
   │   │ + pgvector       │      │ cache.t4g.micro    │       │
   │   │ db.t4g.micro     │      │ 캐시·키 휴식·제한   │       │
   │   │ 외부 접근 차단    │      └────────────────────┘       │
   │   └──────────────────┘                                   │
   └───────────────────────────────────────────────────────────┘

   프론트(Vercel) ──HTTPS──▶ 게이트웨이 EIP ──▶ ECS
```

---

## 기존 프로젝트와 어떻게 분리하나

| 겹 | 방법 | 효과 |
|---|---|---|
| **네트워크** | 기본 VPC 를 쓰지 않고 `10.20.0.0/16` 새 VPC 를 만든다. 피어링·공유 서브넷 없음 | 서로의 트래픽이 닿지 않는다 |
| **이름** | 모든 리소스가 `anasudal-*`, ECR 은 `anasudal/api`, SSM 은 `/anasudal/prod/*`, 로그는 `/ecs/anasudal-*` | 콘솔에서 한눈에 구분되고 IAM 으로 범위를 잡을 수 있다 |
| **태그** | 전부 `Project=anasudal` (Terraform `default_tags`) | 비용 분석과 IAM 조건에 쓴다 |
| **권한** | 전용 IAM 사용자 `anasudal-deploy` — 위 이름·태그 범위 밖은 변경·삭제가 **명시적으로 거부** | 실수로도 기존 프로젝트를 못 건드린다 |

### 전용 IAM 사용자

`infra/iam/create-deploy-user.sh` 를 AWS CloudShell 에 붙여넣어 실행하면 만들어집니다.

| 정책 | 허용 범위 |
|---|---|
| `anasudal-deploy-core` | ECR `anasudal/*` · ECS `anasudal-*` · 로그 `/ecs/anasudal-*` · SSM 파라미터 `/anasudal/*` · IAM 역할 `anasudal-*` · SSM 세션은 `Project=anasudal` 태그 붙은 인스턴스만 |
| `anasudal-deploy-infra` | VPC·RDS·ElastiCache 생성 권한. 단 **태그가 `anasudal` 이 아닌 리소스의 삭제·변경은 Deny** |

권한 상승도 막아뒀습니다. 이 사용자는 IAM 사용자·정책을 만들거나 고칠 수 없고, Organizations·결제 설정도 못 봅니다.

### 계정에 이미 있던 것 — `syak` (2026-09-13 확인)

계정 `181250800061` 에는 `syak` 프로젝트가 **기본 VPC 안에, 태그 없이** 돌고 있습니다.

| 종류 | 리소스 |
|---|---|
| VPC | `vpc-01e3c57b548ab96e2` (기본 VPC, 172.31.0.0/16) — 서브넷 4개 |
| EC2 | `i-0321c7a1c01c26428` (syak-backend, t3.micro, running) |
| 보안그룹 | `default`, `syak-rds-sg`, `syak-backend-sg` |
| RDS | `syak-postgres` (PostgreSQL, db.t3.micro, 외부 비공개) |
| ECS | 클러스터 `syak` / 서비스 `syak-backend` |
| ECR | `syak-backend` |

태그가 없으므로 태그 조건만으로는 부족합니다. 그래서 **위 ARN 들을 정책에 직접 박아 무조건 거부**합니다
(`HardDenyExistingSyakProject`). 태그와 무관하므로 재태깅으로 우회할 수 없습니다.

### 실제로 막히는지 확인한 결과

정책을 읽어 추론한 것이 아니라 `--dry-run` 으로 실제 호출해 확인했습니다.

| 시도 | 결과 |
|---|---|
| syak EC2 종료 / 중지 | 거부 |
| 기본 VPC 삭제 / 속성 변경 | 거부 |
| syak 서브넷 삭제 | 거부 |
| syak 보안그룹에 22번 포트 열기 | 거부 |
| 기본 VPC 에 보안그룹 생성 | 거부 |
| syak EC2·RDS 에 `Project=anasudal` 태그 붙이기 | 거부 (우회 시도 차단) |
| syak ECR 리포 삭제 / ECS 서비스 삭제 | 거부 |
| 새 VPC 생성 · EIP 할당 · 태그 포함 인스턴스 실행 | 허용 |
| ECR `anasudal/*` · ECS `anasudal-*` 접근 | 허용 |

> **남은 한계 두 가지.**
> ① 기본 VPC 에 태그를 *붙이는* 것 자체는 막히지 않습니다. 생성 시 태깅(`ec2:CreateAction`)을 허용해야
> Terraform 이 동작하는데, 그 예외를 EC2 가 `CreateTags` 에도 적용하기 때문입니다. 다만 ARN 거부는
> 태그와 무관하므로 **태그를 붙여도 삭제·변경은 여전히 막힙니다** — 실질적 노출은 없습니다.
> ② `syak` 이 앞으로 **새로** 만드는 리소스는 ARN 목록에 없습니다. 태그 없는 새 리소스는 태그 조건
> (`StringNotEqualsIfExists`)이 잡아주지만, 완전한 격리를 원하면 AWS Organizations 로 **계정을 분리**하는
> 것이 유일한 확실한 답입니다.

---

## 구성 결정과 이유

| 결정 | 이유 |
|---|---|
| **ALB 대신 EC2 + nginx** | 요구사항(외부 게이트웨이 = EC2). ALB 고정비(월 ~$20)도 아낀다. 태스크 IP 가 바뀌는 건 Cloud Map 내부 DNS 로 흡수 |
| **SSH 없이 SSM 만** | 22번 포트·키페어 없음. IAM 권한만으로 셸과 포트포워딩. 접속 기록이 CloudTrail 에 남는다 |
| **Fargate Spot** | 해커톤 기간 비용 ~70% 절감. 운영 전환은 `capacity_provider = "FARGATE"` 한 줄 |
| **SSM Parameter Store** | Secrets Manager(비밀당 월 $0.4) 대신 무료. 태스크 정의 `secrets` 로 주입돼 이미지·코드에 키가 없다 |
| **RDS·Redis 는 프라이빗** | 인터넷에서 직접 못 닿는다. 접근은 게이트웨이를 통한 SSM 포트포워딩뿐 |
| **NAT 단일 AZ** | Gemini 호출용 출구. 이중화하면 AZ 당 월 $32 추가 — MVP 엔 과하다 |
| **Terraform + lifecycle ignore** | 인프라는 Terraform, 태스크 정의 리비전은 CI 가 갱신 |

### Gemini 키는 SSM 에 나눠 둔다

| 파라미터 | 내용 |
|---|---|
| `/anasudal/prod/GEMINI_API_KEYS` | 답변·임베딩용 (콤마로 여러 개). 한 키가 429 면 앱이 다음 키로 넘어간다 |
| `/anasudal/prod/GEMINI_SUMMARY_KEY` | 질문 요약 전용. 답변 쿼터와 분리 |
| `/anasudal/prod/DATABASE_URL` · `REDIS_URL` · `CORS_ORIGINS` · `TOP_K` | 나머지 앱 설정 |

키 휴식 상태는 ElastiCache 에 공유돼서, 태스크가 여러 개여도 막힌 키를 반복해 때리지 않습니다.

---

## 파일

```
infra/iam/
  create-deploy-user.sh        CloudShell 에서 실행 → 전용 IAM 사용자 + 정책 2개 + 액세스 키
  anasudal-deploy-core.json    ECR·ECS·로그·SSM·IAM 역할 (anasudal-* 한정)
  anasudal-deploy-infra.json   VPC·RDS·ElastiCache + 타 프로젝트 보호 Deny
infra/terraform/
  versions.tf   provider·원격 상태(주석)     vpc.tf         VPC·서브넷·NAT·보안그룹 3개
  rds.tf        PG16 + 랜덤 비밀번호         elasticache.tf Redis 7 + SG + REDIS_URL
  ssm.tf        앱 설정 파라미터             ecr.tf         리포지토리 + 최근 10개 보관
  ecs.tf        Cloud Map·클러스터·태스크·서비스
  iam.tf        태스크실행/태스크/게이트웨이/GitHub OIDC 역할
  gateway.tf    EC2 + EIP + user-data(nginx)  outputs.tf    진입 IP·인스턴스 id·ECR URL
infra/scripts/
  login.ps1      ★ 첫 실행 (Windows PowerShell) — 로그인 → IAM 사용자 → 프로필 등록 → 루트 키 정리
  login.sh       ★ 첫 실행 (Linux/macOS/CloudShell) — 위와 동일
  check-aws.sh   인증·권한·계정 현황 점검 (기존 프로젝트 리소스도 같이 보여준다)
  first-push.sh  첫 이미지 ECR 푸시 + 강제 재배포     db-tunnel.sh  localhost:15432 → RDS (SSM)
  db-init.sh     터널 통해 스키마·데이터 적재          shell.sh      게이트웨이 SSM 셸
.github/workflows/deploy.yml   main push → ECR → 태스크정의 렌더 → ECS 롤링 배포
```

---

## 배포 순서

```bash
# 0. 로그인 + 전용 IAM 사용자 (1회, 이것만 하면 된다)
#    Windows PowerShell:
powershell -ExecutionPolicy Bypass -File .\infra\scripts\login.ps1
#    Linux / macOS / CloudShell:
bash infra/scripts/login.sh
#    루트 액세스 키 두 줄만 입력하면 나머지는 자동:
#    IAM 사용자 anasudal-deploy 생성 → 새 키를 anasudal 프로필에 등록
#    → 루트 키 정리 → 권한 점검

export AWS_PROFILE=anasudal

# 2. 인프라
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars   # gemini_api_keys, gemini_summary_key, cors_origins
terraform init && terraform apply               # ~12분 (RDS 가 대부분)

# 3. 첫 이미지 (ECR 이 비어 있어 서비스가 아직 못 뜬다)
../scripts/first-push.sh

# 4. DB 초기화 — 터미널 A 에서 터널, B 에서 적재
../scripts/db-tunnel.sh
python ../../scripts/kb_to_csv.py && ../scripts/db-init.sh

# 5. 확인
curl http://$(terraform output -raw gateway_public_ip)/health
python ../../scripts/smoke_api.py http://$(terraform output -raw gateway_public_ip)

# 6. 이후 배포: GitHub Secrets 에 AWS_DEPLOY_ROLE_ARN 넣고 main 에 push
```

---

## 운영

| 작업 | 명령 |
|---|---|
| 게이트웨이 셸 | `infra/scripts/shell.sh` → `sudo tail -f /var/log/nginx/error.log` |
| API 로그 | CloudWatch `/ecs/anasudal-prod/api` |
| DB 접속 | `db-tunnel.sh` 후 `psql "postgresql://anasudal:<pw>@localhost:15432/anasudal?sslmode=require"` |
| 키 상태 확인 | `curl http://<게이트웨이>/health` — 어느 Gemini 키가 쉬는 중인지 |
| MV 갱신 | `SELECT refresh_all_mvs();` (가격 공시 갱신 후) |
| 세션 정리 | `SELECT purge_expired_sessions();` |
| 스케일 | `aws ecs update-service --cluster anasudal-prod --service api --desired-count 2` |
| 키 교체 | `aws ssm put-parameter --name /anasudal/prod/GEMINI_API_KEYS --overwrite --type SecureString --value "키1,키2"` 후 재배포 |
| **전체 철거** | `cd infra/terraform && terraform destroy` — 이 프로젝트 리소스만 지운다 |

---

## 비용 (서울 리전, 월 추정)

| 항목 | 사양 | 월 |
|---|---|---|
| RDS | db.t4g.micro + gp3 20GB | ~$15 |
| Fargate Spot | 0.5 vCPU / 1 GB × 1 | ~$6 |
| 게이트웨이 EC2 | t4g.micro + EIP | ~$8 |
| ElastiCache | cache.t4g.micro ×1 | ~$12 |
| NAT Gateway | 1 AZ + 소량 트래픽 | ~$33 |
| ECR / CloudWatch / SSM | | ~$2 |
| **합계** | | **~$76** |

NAT 가 절반입니다. 더 줄이려면 ECS 태스크를 퍼블릭 서브넷에 두고 공인 IP 를 붙여 NAT 를 없앨 수 있지만,
그러면 태스크가 공인 IP 를 갖게 돼 보안그룹(8000 은 게이트웨이만)이 유일한 방벽이 됩니다. 심사 기간엔 허용 가능한 절충입니다.

해커톤이 끝나면 `terraform destroy` 로 전부 내려 과금을 멈추세요.

---

## 아직 안 한 것

- **HTTPS** — 도메인이 정해지면 게이트웨이에 certbot 추가(user-data 10줄). Vercel 에서 호출하려면 필수입니다(mixed content).
- **terraform plan 미실행** — 이 PC 에 Terraform 이 없어 HCL 파서로 문법·참조만 검사했습니다. 배포 전 `terraform init && plan` 필요.
- **오토스케일** — 심사 트래픽엔 불필요. 필요하면 `aws_appautoscaling_target` 추가.
- **RDS 삭제 보호** — 해커톤 편의로 `deletion_protection = false`. 운영 전환 시 켜세요.
