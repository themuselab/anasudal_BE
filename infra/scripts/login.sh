#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# 한 번만 실행하면 끝나는 스크립트.
#
#   bash infra/scripts/login.sh
#
# 당신이 하는 것   : 루트 액세스 키 두 줄 입력 (화면 안내대로)
# 스크립트가 하는 것: 인증 확인 → IAM 사용자 anasudal-deploy 생성 → 새 키를
#                     anasudal 프로필에 자동 등록 → 루트 키 정리 → 권한 점검
#
# 키를 복사해서 어디에 붙여넣을 필요가 없습니다. 중간에 화면에도 찍지 않습니다.
# ─────────────────────────────────────────────────────────────────────────────
set -uo pipefail

BOOT=root-bootstrap      # 루트 키를 잠깐 담아두는 프로필 (끝나면 지운다)
TARGET=anasudal          # 앞으로 계속 쓸 프로필
REGION=ap-northeast-2
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

KEYFILE=""
cleanup () { [ -n "$KEYFILE" ] && [ -f "$KEYFILE" ] && rm -f "$KEYFILE"; }
trap cleanup EXIT INT TERM

say () { printf '\n\033[1m%s\033[0m\n' "$*"; }

# ── 1. 루트 자격 증명 ───────────────────────────────────────────────────────
say "1/5  루트 로그인"

if aws sts get-caller-identity --profile "$BOOT" >/dev/null 2>&1; then
  echo "  이미 로그인돼 있습니다. 넘어갑니다."
else
  cat <<'HOWTO'
  루트 액세스 키가 필요합니다. 아직 없으면 이렇게 만드세요 (콘솔, 1분):

    AWS 콘솔 우측 상단 계정 이름
      → 보안 자격 증명 (Security credentials)
      → 아래로 스크롤 → 액세스 키 → 액세스 키 만들기
      → 경고 체크박스 확인 → 만들기

  키와 시크릿이 그 화면에서만 보입니다. 아래에 그대로 붙여넣으세요.
  (붙여넣기: 마우스 오른쪽 버튼 / 시크릿은 입력해도 화면에 안 보일 수 있습니다)

HOWTO
  aws configure --profile "$BOOT"
fi

CALLER=$(aws sts get-caller-identity --profile "$BOOT" --query Arn --output text 2>&1)
if [ $? -ne 0 ]; then
  echo "  ✗ 인증 실패:"; echo "$CALLER" | head -3 | sed 's/^/      /'
  echo "      키를 잘못 붙여넣었을 수 있습니다. 다시 실행해 보세요."
  exit 1
fi
ACCOUNT=$(aws sts get-caller-identity --profile "$BOOT" --query Account --output text)
echo "  ✓ 계정 $ACCOUNT / $CALLER"

IS_ROOT=no
case "$CALLER" in *:root) IS_ROOT=yes ;; esac

# ── 2. IAM 사용자 만들기 ────────────────────────────────────────────────────
say "2/5  전용 IAM 사용자 만들기"
KEYFILE=$(mktemp "${TMPDIR:-/tmp}/anasudal-key.XXXXXX")
if ! AWS_PROFILE="$BOOT" ANASUDAL_KEY_OUT="$KEYFILE" bash "$DIR/iam/create-deploy-user.sh"; then
  echo "  ✗ 생성 실패 — 위 오류를 확인하세요."
  exit 1
fi

# ── 3. 새 키를 프로필에 등록 ────────────────────────────────────────────────
say "3/5  anasudal 프로필에 등록"
# shellcheck disable=SC1090
. "$KEYFILE"
aws configure set aws_access_key_id     "$AWS_ACCESS_KEY_ID"     --profile "$TARGET"
aws configure set aws_secret_access_key "$AWS_SECRET_ACCESS_KEY" --profile "$TARGET"
aws configure set region "$REGION" --profile "$TARGET"
aws configure set output json      --profile "$TARGET"
cleanup; KEYFILE=""
echo "  ✓ ~/.aws/credentials 의 [$TARGET] 에 저장했습니다."

# 새 키는 AWS 내부에 퍼지는 데 몇 초 걸린다 — 될 때까지 몇 번 시도한다.
printf "  새 키가 활성화되기를 기다리는 중"
OK=no
for _ in $(seq 1 12); do
  if aws sts get-caller-identity --profile "$TARGET" >/dev/null 2>&1; then OK=yes; break; fi
  printf "."; sleep 3
done
echo
if [ "$OK" = yes ]; then
  echo "  ✓ $(aws sts get-caller-identity --profile "$TARGET" --query Arn --output text)"
else
  echo "  ⚠ 아직 응답이 없습니다. 1분쯤 뒤 이 명령으로 확인해 보세요:"
  echo "      aws sts get-caller-identity --profile $TARGET"
fi

# ── 4. 루트 키 정리 ─────────────────────────────────────────────────────────
say "4/5  루트 키 정리"
if [ "$IS_ROOT" = yes ] && [ "$OK" = yes ]; then
  echo "  루트 키는 계정 전체를 열 수 있어서, 이제 없애는 게 안전합니다."
  echo "  (새 키가 잘 동작하는 것을 위에서 확인했습니다)"
  printf "  지금 삭제할까요? 삭제하려면 yes 입력: "
  read -r ANS
  if [ "$ANS" = "yes" ]; then
    ROOT_KEY=$(aws iam list-access-keys --profile "$BOOT" \
               --query 'AccessKeyMetadata[0].AccessKeyId' --output text 2>/dev/null)
    if [ -n "$ROOT_KEY" ] && [ "$ROOT_KEY" != "None" ] \
       && aws iam delete-access-key --access-key-id "$ROOT_KEY" --profile "$BOOT" 2>/dev/null; then
      echo "  ✓ 루트 키 삭제: $ROOT_KEY"
    else
      echo "  ⚠ CLI 로 지우지 못했습니다. 콘솔에서 지워주세요:"
      echo "      계정 이름 → 보안 자격 증명 → 액세스 키 → 삭제"
    fi
  else
    echo "  건너뜁니다. 나중에 콘솔에서 꼭 지우세요 (계정 이름 → 보안 자격 증명)."
  fi
  # 로컬에 남은 루트 키도 지운다
  aws configure set aws_access_key_id     "" --profile "$BOOT" 2>/dev/null
  aws configure set aws_secret_access_key "" --profile "$BOOT" 2>/dev/null
  echo "  ✓ 이 PC 의 [$BOOT] 프로필에서도 키를 비웠습니다."
else
  echo "  루트가 아니거나 확인이 끝나지 않아 건너뜁니다."
fi

# ── 5. 점검 ─────────────────────────────────────────────────────────────────
say "5/5  권한·계정 점검"
AWS_PROFILE="$TARGET" bash "$DIR/scripts/check-aws.sh"

say "끝났습니다"
cat <<DONE
  앞으로는 이 프로필을 씁니다:

      export AWS_PROFILE=$TARGET

  다음 단계는 인프라 생성입니다:

      cd infra/terraform && terraform init && terraform apply
DONE
