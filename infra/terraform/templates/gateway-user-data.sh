#!/bin/bash
# =============================================================================
#  게이트웨이 부팅 스크립트
#
#  이 파일은 Terraform templatefile() 로 렌더된다. 따라서 $${...} 는 Terraform 이
#  먼저 치환한다. 셸 변수는 반드시 중괄호 없이 $VAR 로 쓸 것.
#  (중괄호가 꼭 필요하면 $${VAR} 로 이스케이프)
#
#  진행 상황: /var/log/anasudal-init.log
# =============================================================================
set -uo pipefail
exec > >(tee -a /var/log/anasudal-init.log) 2>&1
echo "=== anasudal init 시작: $(date -Is) ==="

CLUSTER="${cluster_name}"
REGION="${region}"
PREFIX="${ssm_prefix}"
DB_USER="${db_username}"
DB_NAME="${db_name}"
DATA_DIR=/var/lib/anasudal

retry () {  # retry <횟수> <명령...>
  local n=$1; shift
  local i=1
  until "$@"; do
    if [ $i -ge $n ]; then echo "!! 실패 $i/$n: $*"; return 1; fi
    echo ".. 재시도 $i/$n: $*"; sleep 5; i=$((i+1))
  done
  return 0
}

# ── 1. ECS 에이전트를 우리 클러스터에 등록 ───────────────────────────────────
mkdir -p /etc/ecs
{
  echo "ECS_CLUSTER=$CLUSTER"
  echo "ECS_ENABLE_CONTAINER_METADATA=true"
  echo "ECS_ENABLE_SPOT_INSTANCE_DRAINING=true"
  echo 'ECS_AVAILABLE_LOGGING_DRIVERS=["json-file","awslogs"]'
} >> /etc/ecs/ecs.config
echo "ECS_CLUSTER=$CLUSTER 설정"

# ── 2. 도커 기동 ─────────────────────────────────────────────────────────────
systemctl enable --now docker
retry 30 docker info >/dev/null

# ── 3. AWS CLI 확보 (SecureString 을 읽어야 한다) ────────────────────────────
# ECS 최적화 AMI 에 aws CLI 가 없을 수 있다. 없으면 컨테이너로 대신 쓴다.
if ! command -v aws >/dev/null 2>&1; then
  dnf install -y awscli-2 >/dev/null 2>&1 || dnf install -y aws-cli >/dev/null 2>&1 || true
fi
get_param () {  # get_param <이름> ; 복호화해서 값만 출력
  if command -v aws >/dev/null 2>&1; then
    aws ssm get-parameter --name "$1" --with-decryption --region "$REGION" \
        --query Parameter.Value --output text
  else
    docker run --rm --network host amazon/aws-cli:latest \
        ssm get-parameter --name "$1" --with-decryption --region "$REGION" \
        --query Parameter.Value --output text
  fi
}

DB_PASS=""
for i in 1 2 3 4 5 6; do
  DB_PASS=$(get_param "$PREFIX/DB_PASSWORD" 2>/dev/null || true)
  [ -n "$DB_PASS" ] && [ "$DB_PASS" != "None" ] && break
  echo ".. DB_PASSWORD 대기 $i/6"; sleep 10
done
if [ -z "$DB_PASS" ] || [ "$DB_PASS" = "None" ]; then
  echo "!! SSM 에서 DB_PASSWORD 를 읽지 못했습니다. Postgres 를 띄우지 않습니다."
  exit 1
fi

# ── 4. Postgres(pgvector) + Redis ────────────────────────────────────────────
# 데이터는 EBS 위 $DATA_DIR 에 남는다. 컨테이너를 지우거나 ECS 가 재배포해도 유지된다.
mkdir -p "$DATA_DIR/pg" "$DATA_DIR/redis"

retry 5 docker pull pgvector/pgvector:pg16
docker rm -f anasudal-pg >/dev/null 2>&1 || true
docker run -d --name anasudal-pg --restart always \
  -p 127.0.0.1:5432:5432 \
  -e POSTGRES_USER="$DB_USER" \
  -e POSTGRES_PASSWORD="$DB_PASS" \
  -e POSTGRES_DB="$DB_NAME" \
  -e PGDATA=/var/lib/postgresql/data/pgdata \
  -v "$DATA_DIR/pg":/var/lib/postgresql/data \
  --shm-size=256m \
  pgvector/pgvector:pg16

retry 5 docker pull redis:7-alpine
docker rm -f anasudal-redis >/dev/null 2>&1 || true
docker run -d --name anasudal-redis --restart always \
  -p 127.0.0.1:6379:6379 \
  -v "$DATA_DIR/redis":/data \
  redis:7-alpine redis-server --appendonly yes \
    --maxmemory 128mb --maxmemory-policy allkeys-lru

# Postgres 가 받을 준비가 될 때까지 기다렸다가 확장을 만든다
for i in $(seq 1 60); do
  if docker exec anasudal-pg pg_isready -U "$DB_USER" -d "$DB_NAME" >/dev/null 2>&1; then
    echo "Postgres 준비됨 ($i 회차)"
    break
  fi
  sleep 2
done
docker exec anasudal-pg psql -U "$DB_USER" -d "$DB_NAME" \
  -c 'CREATE EXTENSION IF NOT EXISTS vector;' || echo "!! vector 확장 생성 실패 - db-init.sh 로 다시 시도하세요"

# ── 5. nginx (80 → API 8000) ─────────────────────────────────────────────────
dnf install -y nginx
# AL2023 기본 nginx.conf 에 default_server 블록이 있어 충돌한다. 통째로 교체한다.
cat > /etc/nginx/nginx.conf <<'NGINXCONF'
user nginx;
worker_processes auto;
error_log /var/log/nginx/error.log notice;
pid /run/nginx.pid;

events { worker_connections 1024; }

http {
    include       /etc/nginx/mime.types;
    default_type  application/octet-stream;
    log_format main '$remote_addr - $remote_user [$time_local] "$request" '
                    '$status $body_bytes_sent "$http_referer" "$http_user_agent"';
    access_log  /var/log/nginx/access.log  main;
    sendfile        on;
    keepalive_timeout  65;
    server_tokens   off;

    # API 가 아직 안 떠 있을 때 502 대신 기다렸다가 돌려준다
    upstream api {
        server 127.0.0.1:8000 max_fails=0;
        keepalive 16;
    }

    server {
        listen 80 default_server;
        server_name _;
        client_max_body_size 10m;

        location / {
            proxy_pass http://api;
            proxy_http_version 1.1;
            proxy_set_header Host              $host;
            proxy_set_header Connection        "";
            proxy_set_header X-Real-IP         $remote_addr;
            proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_connect_timeout 5s;
            proxy_read_timeout  120s;   # Gemini 호출이 길 수 있다
            proxy_send_timeout  120s;
        }
    }
}
NGINXCONF
nginx -t && systemctl enable --now nginx && systemctl reload nginx || {
  echo "!! nginx 설정 오류"; nginx -t;
}

# ── 6. ECS 에이전트 ─────────────────────────────────────────────────────────
# ecs.service 에는 After=cloud-final.service 가 걸려 있다. user-data 는 그 cloud-final
# 안에서 돌기 때문에, 여기서 블로킹으로 `systemctl restart ecs` 를 부르면
#   user-data → systemctl 완료 대기 → ecs.service → cloud-final 완료 대기 → user-data
# 로 서로를 기다리는 교착에 빠진다 (실제로 당했다. 부팅이 영원히 끝나지 않는다).
# --no-block 으로 요청만 걸어두면 cloud-final 이 끝난 뒤 systemd 가 알아서 시작한다.
systemctl enable ecs || true
systemctl --no-block restart ecs || true

echo "=== anasudal init 끝: $(date -Is) ==="
echo "확인: docker ps ; systemctl status nginx ecs ; curl -s localhost/health"
