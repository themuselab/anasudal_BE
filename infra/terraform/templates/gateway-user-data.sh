#!/bin/bash
set -euxo pipefail
# Amazon Linux 2023: SSM Agent 내장. nginx만 올리고 ECS 태스크(Cloud Map DNS)로 프록시한다.

dnf -y update
dnf -y install nginx

API_HOST=$(aws ssm get-parameter --region ${region} --name "${ssm_prefix}/API_INTERNAL_HOST" --query Parameter.Value --output text)

cat >/etc/nginx/conf.d/api.conf <<EOF
# ECS 태스크 IP는 배포마다 바뀐다 → nginx가 캐시하지 않도록 VPC DNS로 매번 재해석
resolver 169.254.169.253 valid=10s ipv6=off;

map \$http_upgrade \$connection_upgrade { default upgrade; '' close; }

server {
    listen 80 default_server;
    server_name _;

    client_max_body_size 1m;

    location /health {
        set \$api http://$${API_HOST}:8000;
        proxy_pass \$api;
    }

    location /v1/ {
        set \$api http://$${API_HOST}:8000;
        proxy_pass \$api;
        proxy_http_version 1.1;
        proxy_set_header Host              \$host;
        proxy_set_header X-Real-IP         \$remote_addr;
        proxy_set_header X-Forwarded-For   \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header Upgrade           \$http_upgrade;
        proxy_set_header Connection        \$connection_upgrade;
        proxy_read_timeout 90s;
        proxy_buffering off;              # SSE (/chat/ask/stream)
        proxy_cache off;
    }

    location /docs { set \$api http://$${API_HOST}:8000; proxy_pass \$api; }
    location /openapi.json { set \$api http://$${API_HOST}:8000; proxy_pass \$api; }

    location / { return 404; }
}
EOF

rm -f /etc/nginx/conf.d/default.conf || true
nginx -t
systemctl enable --now nginx
systemctl restart nginx
