# 안아수달 AWS 인프라

계정 `181250800061` 에는 기존 프로젝트 `syak` 이 이미 돌고 있습니다.
**네트워크·이름·권한 세 겹으로 분리**했고, 실제로 막히는지 `--dry-run` 으로 확인했습니다.

해커톤 검증용이라 **비용을 최소화**했습니다 — 월 약 $24. EC2 한 대에 전부 올립니다.

---

## 전체 그림

```
                          인터넷
                            │ :80
   ┌────────────────────────▼──────────────────────────────┐
   │  VPC  anasudal-prod   10.20.0.0/16                     │
   │  퍼블릭 서브넷 10.20.0.0/24 · 10.20.1.0/24             │
   │  (NAT Gateway 없음 — 인스턴스가 EIP 로 직접 나간다)      │
   │                                                        │
   │   ┌──────────────────────────────────────────────┐    │
   │   │  EC2  t3.small  (EIP 고정, SSH 포트 없음)      │    │
   │   │                                               │    │
   │   │   nginx            :80  ──┐                   │    │
   │   │                           ▼                   │    │
   │   │   API (ECS 태스크)      127.0.0.1:8000         │    │
   │   │     · ECR anasudal/api 에서 pull               │    │
   │   │     · 설정·비밀은 SSM Parameter Store 에서      │    │
   │   │         │              │                      │    │
   │   │         ▼              ▼                      │    │
   │   │   Postgres 16      Redis 7                    │    │
   │   │   + pgvector       (도커 컨테이너)             │    │
   │   │   127.0.0.1:5432   127.0.0.1:6379             │    │
   │   │         └──────┬───────┘                      │    │
   │   │         EBS 30GB  /var/lib/anasudal            │    │
   │   └──────────────────────────────────────────────┘    │
   └────────────────────────────────────────────────────────┘

   프론트(Vercel) ──HTTPS──▶ CloudFront ──HTTP──▶ 게이트웨이 EIP ──▶ nginx ──▶ API
                            (*.cloudfront.net 인증서, 도메인 불필요)
   관리자 ──────── SSM Session Manager ────▶ 셸 / DB 포트포워딩
```

Postgres·Redis·API 는 모두 `127.0.0.1` 에만 바인딩됩니다. 밖에서 열린 포트는 80/443 뿐입니다.

---

## 왜 이렇게 만들었나

| 결정 | 이유 |
|---|---|
| **ECS 를 Fargate 아닌 EC2 에서** | Fargate 태스크는 프라이빗 서브넷에 있어 ECR·Gemini 로 나가려면 NAT Gateway(월 ~$43)가 필요했다. EC2 에 올리면 NAT 가 통째로 사라진다 |
| **Postgres·Redis 를 컨테이너로** | RDS(월 ~$19) + ElastiCache(월 ~$17) 대신. 데이터는 EBS 에 남아 재부팅·재배포에도 유지된다 |
| **`network_mode = "host"`** | 태스크가 인스턴스의 localhost 를 그대로 본다. Cloud Map 내부 DNS 가 필요 없고 nginx 도 `127.0.0.1:8000` 으로 바로 프록시한다 |
| **x86(t3.small), ARM 아님** | API 이미지가 GitHub Actions(ubuntu-latest, amd64)에서 평범한 `docker build` 로 만들어진다. ARM 은 월 $3 싸지만 멀티아치 빌드가 필요해 값어치가 없다 |
| **t3.small (2GB)** | Postgres + Redis + API + nginx 를 한 대에 올리려면 1GB 는 빠듯하다 |
| **SSH 없이 SSM 만** | 22번 포트도 키페어도 없다. 접속 기록이 CloudTrail 에 남는다 |
| **SSM Parameter Store** | Secrets Manager(비밀당 월 $0.4) 대신 무료. 태스크 정의 `secrets` 로 주입돼 이미지·코드에 키가 없다 |

### 이 선택으로 잃은 것

- **자동 백업·시점 복원이 없습니다.** RDS 였다면 따라왔을 기능입니다.
- **인스턴스가 죽으면 DB 도 같이 내려갑니다.** 단일 장애점입니다.
- **`user_data` 를 바꿔 `terraform apply` 하면 인스턴스가 교체되고 EBS 와 함께 DB 데이터도 사라집니다.**
  지식베이스는 `db-init.sh` 로 다시 적재할 수 있지만 세션 기록은 복구되지 않습니다.

심사 중 데이터 유실이 치명적이라면 `git log` 에서 `rds.tf` / `elasticache.tf` 를 되살리면 됩니다.
`DATABASE_URL` · `REDIS_URL` 만 바뀌고 앱 코드는 그대로입니다. 월 ~$40 이 됩니다.

---

## 기존 프로젝트(syak)와의 분리

### 계정에 이미 있던 것 (2026-09-13 확인)

`syak` 은 **기본 VPC 안에** 있었고 **태그가 없었습니다**. 지금은 전부 `Project=syak` 을 붙여 뒀습니다.

| 종류 | 리소스 |
|---|---|
| VPC | `vpc-01e3c57b548ab96e2` (기본 VPC, 172.31.0.0/16) — 서브넷 4개 |
| EC2 | `i-0321c7a1c01c26428` (syak-backend, t3.micro) |
| 보안그룹 | `syak-rds-sg`, `syak-backend-sg` |
| RDS | `syak-postgres` |
| ECS | 클러스터 `syak` / 서비스 `syak-backend` |
| ECR | `syak-backend` |

### 세 겹

| 겹 | 방법 |
|---|---|
| **네트워크** | 기본 VPC 를 쓰지 않고 `10.20.0.0/16` 새 VPC. 피어링 없음 |
| **이름·태그** | 모든 리소스가 `anasudal-*` 이고 `Project=anasudal` |
| **권한** | 배포용 IAM 사용자 `anasudal-deploy` 는 위 범위 밖의 변경·삭제가 **명시적으로 거부**된다 |

정책 두 개가 이를 강제합니다.

| 정책 | 내용 |
|---|---|
| `anasudal-deploy-core` | ECR `anasudal/*` · ECS `anasudal-*` · 로그 `/ecs/anasudal-*` · SSM `/anasudal/*` · IAM 역할 `anasudal-*` · SSM 세션은 `Project=anasudal` 태그 인스턴스만 |
| `anasudal-deploy-infra` | VPC·EC2 생성 허용. 단 **`HardDenyExistingSyakProject`** 가 syak ARN 들을 무조건 거부하고, 태그가 `anasudal` 이 아닌 리소스의 삭제·변경도 거부 |

권한 상승도 막혀 있습니다. 이 사용자는 IAM 사용자·정책을 만들거나 고칠 수 없고, Organizations·결제에도 닿지 않습니다.

### 실제로 막히는지 확인한 결과

정책을 읽어 추론한 것이 아니라 `--dry-run` 으로 실제 호출해 확인했습니다.

| 시도 | 결과 |
|---|---|
| syak EC2 종료 / 중지 | 거부 |
| 기본 VPC 삭제 / 속성 변경 | 거부 |
| syak 서브넷 삭제 · 보안그룹에 22번 열기 | 거부 |
| 기본 VPC 에 보안그룹 생성 | 거부 |
| syak EC2·RDS 태그를 `anasudal` 로 바꾸기 | 거부 (우회 시도 차단) |
| syak ECR 리포·ECS 서비스 삭제 | 거부 |
| 새 VPC 생성 · EIP 할당 · 태그 포함 인스턴스 실행 | 허용 |

> **남은 한계.** `syak` 이 앞으로 **새로** 만드는 리소스는 ARN 목록에 없습니다.
> 태그 없는 새 리소스는 태그 조건(`StringNotEqualsIfExists`)이 잡아주지만,
> 완전한 격리를 원하면 AWS Organizations 로 **계정을 분리**하는 것이 유일한 확실한 답입니다.

---

## 현재 배포 상태 (2026-09-13)

| | |
|---|---|
| **API (HTTPS)** | `https://d180wuyf09twzy.cloudfront.net` ← 프론트는 이 주소를 쓴다 |
| API (직통 HTTP) | `http://3.35.39.226` — 디버깅용. 브라우저에선 mixed content 로 막힌다 |
| 인스턴스 | `i-002703d3b1021d0f9` (t3.small, ap-northeast-2a) |
| 컨테이너 | api(healthy) · ecs-agent(healthy) · anasudal-pg · anasudal-redis |
| DB | region 218 · institution 2,866 · institution_area_price 12,925 · kb_chunk 1,473(전량 임베딩) |
| CI 역할 | `arn:aws:iam::181250800061:role/anasudal-prod-gha-deploy` |

`scripts/smoke_api.py` 전 항목 통과 (HTTPS 경유, 실제 Gemini 호출 포함).

---

## 처음부터 배포하기

필요한 도구: AWS CLI, Terraform, Docker, **Session Manager 플러그인**

```bash
winget install Hashicorp.Terraform Amazon.SessionManagerPlugin
```

```bash
# 1. 로그인 + 전용 IAM 사용자 (1회)
powershell -ExecutionPolicy Bypass -File .\infra\scripts\login.ps1     # Windows
bash infra/scripts/login.sh                                            # Linux/macOS

# 2. Gemini 키 넣기 (메모장이 열립니다)
powershell -ExecutionPolicy Bypass -File .\infra\scripts\set-secrets.ps1

# 3. 인프라 (~4분)
export AWS_PROFILE=anasudal
cd infra/terraform && terraform init && terraform apply

# 4. 첫 이미지 — ECR 이 비어 있어 태스크가 아직 못 뜬다
../scripts/first-push.sh

# 5. DB 초기화 — 터미널 A 에서 터널, B 에서 적재
../scripts/db-tunnel.sh
python ../../scripts/kb_to_csv.py && ../scripts/db-init.sh

# 6. 확인
python ../../scripts/smoke_api.py $(terraform output -raw api_https_url)
```

> **psql 이 없다면** `db-init.sh` 대신 도커로 같은 일을 할 수 있습니다(설치 불필요).
> 터널을 연 상태에서:
> ```bash
> PW=$(aws ssm get-parameter --name /anasudal/prod/DB_PASSWORD --with-decryption --query Parameter.Value --output text)
> SQL=$(cygpath -w "$PWD/db"); DATA=$(cygpath -w "$PWD/data")
> docker run --rm -e PGPASSWORD="$PW" -v "$SQL":/sql -v "$DATA":/data postgres:16 psql -h host.docker.internal -p 15432 -U anasudal -d anasudal -v ON_ERROR_STOP=1 -v csv_dir=/data -f /sql/01_schema.sql
> ```
> `cygpath` 는 Git Bash 전용입니다. Linux/macOS 에서는 경로를 그대로 쓰고 `host.docker.internal` 대신 `--network host` 를 씁니다.

### 프론트엔드 연결

CORS 는 SSM 파라미터에 있습니다. Vercel 주소를 넣고 재배포하세요.

```bash
aws ssm put-parameter --name /anasudal/prod/CORS_ORIGINS --overwrite --type String --value "https://<당신의앱>.vercel.app,http://localhost:5173"
aws ecs update-service --cluster anasudal-prod --service api --force-new-deployment
```

---

## 운영

| 작업 | 명령 |
|---|---|
| 인스턴스 셸 | `infra/scripts/shell.sh` |
| 부팅 로그 | 셸에서 `sudo cat /var/log/anasudal-init.log` |
| 컨테이너 상태 | 셸에서 `docker ps` (anasudal-pg, anasudal-redis 가 보여야 정상) |
| API 로그 | CloudWatch `/ecs/anasudal-prod/api` |
| nginx 로그 | 셸에서 `sudo tail -f /var/log/nginx/error.log` |
| DB 접속 | `db-tunnel.sh` 후 `psql "$(aws ssm get-parameter --name /anasudal/prod/DATABASE_URL --with-decryption --query Parameter.Value --output text | sed 's#@127.0.0.1:5432#@localhost:15432#')"` |
| 재배포 | `aws ecs update-service --cluster anasudal-prod --service api --force-new-deployment` |
| 키 교체 | `aws ssm put-parameter --name /anasudal/prod/GEMINI_API_KEYS --overwrite --type SecureString --value "키1,키2"` 후 재배포 |
| **전체 철거** | `cd infra/terraform && terraform destroy` — 이 프로젝트 리소스만 지운다 |

---

## 비용 (서울 리전, 월 추정)

| 항목 | 사양 | 월 |
|---|---|---|
| EC2 | t3.small 온디맨드 | ~$19 |
| EBS | gp3 30GB | ~$3 |
| EIP | 인스턴스에 붙어 있으면 무료 | $0 |
| ECR · CloudWatch · SSM | 소량 | ~$2 |
| **합계** | | **~$24** |

처음 설계(Fargate + NAT + RDS + ElastiCache)는 월 ~$94 였습니다. NAT Gateway 하나가 ~$43 이었습니다.

더 줄이려면 `t3.micro`(1GB, 월 ~$9)로 내릴 수 있지만 Postgres 와 API 를 같이 올리기엔 빠듯합니다.

**해커톤이 끝나면 `terraform destroy` 로 전부 내려 과금을 멈추세요.**

---

## 아직 안 한 것

- **CloudFront↔EC2 구간 암호화** — 뷰어 쪽 HTTPS 는 CloudFront 가 끝냈지만 오리진 구간은 HTTP 입니다. 도메인이 생기면 ACM 인증서로 이 구간도 닫는 것이 맞습니다.
- **자동 백업** — 필요하면 EBS 스냅샷을 하루 한 번 도는 것으로 충분합니다 (DLM 또는 cron).
- **무중단 배포** — 인스턴스가 한 대라 태스크 교체 중 수 초간 502 가 납니다. 심사에는 문제없는 수준입니다.
