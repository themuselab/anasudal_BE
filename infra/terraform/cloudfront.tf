# ── CloudFront: 도메인 없이 HTTPS 를 얻는다 ─────────────────────────────────
#
# 프론트가 Vercel(HTTPS)에 있어서 http://<EIP> 를 직접 부르면 브라우저가
# mixed content 로 막는다. 그런데 Let's Encrypt 는 IP 에 인증서를 못 내준다.
#
# CloudFront 를 앞에 두면 도메인을 사지 않고도 *.cloudfront.net 주소로
# 유효한 HTTPS 를 받는다. 프리티어(월 1TB 전송·1000만 요청)라 사실상 무료다.
#
#   브라우저 ──HTTPS──▶ CloudFront ──HTTP──▶ 게이트웨이 EIP:80 ──▶ nginx ──▶ API
#
# CloudFront ↔ EC2 구간은 HTTP 다. AWS 망 내부지만 암호화되지 않는다.
# 도메인이 생기면 ACM 인증서를 붙여 이 구간도 HTTPS 로 바꾸는 것이 맞다.

resource "aws_cloudfront_distribution" "api" {
  enabled         = true
  comment         = "${local.name} API (HTTPS 종단)"
  price_class     = "PriceClass_200" # 아시아 포함. All 은 남미·호주까지라 불필요
  http_version    = "http2"
  is_ipv6_enabled = true

  origin {
    # CloudFront 오리진은 IP 를 받지 않는다. EIP 에 딸린 공개 DNS 이름을 쓴다
    # (ec2-<ip>.ap-northeast-2.compute.amazonaws.com — EIP 가 고정이라 이 이름도 고정)
    domain_name = aws_eip.gateway.public_dns
    origin_id   = "gateway"

    custom_origin_config {
      http_port                = 80
      https_port               = 443
      origin_protocol_policy   = "http-only" # 오리진에 인증서가 없다
      origin_ssl_protocols     = ["TLSv1.2"]
      origin_read_timeout      = 60 # Gemini 호출이 길다. CloudFront 최대 60초
      origin_keepalive_timeout = 5
    }
  }

  default_cache_behavior {
    target_origin_id       = "gateway"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
    cached_methods         = ["GET", "HEAD"]
    compress               = true

    # API 응답은 캐시하지 않는다. 쿠키·헤더·쿼리스트링을 그대로 오리진에 넘긴다.
    # CachingDisabled / AllViewerExceptHostHeader 는 AWS 관리형 정책 ID(고정값)
    cache_policy_id          = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad"
    origin_request_policy_id = "b689b0a8-53d0-40ab-baf2-68738e2966ac"
  }

  restrictions {
    geo_restriction { restriction_type = "none" }
  }

  viewer_certificate {
    cloudfront_default_certificate = true # *.cloudfront.net 인증서
  }

  tags = { Name = "${local.name}-api" }

  depends_on = [aws_eip_association.gateway]
}
