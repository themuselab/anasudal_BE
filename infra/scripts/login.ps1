# =============================================================================
#  안아수달 - 한 번만 실행하면 끝나는 부트스트랩 (Windows PowerShell 전용)
#
#    powershell -ExecutionPolicy Bypass -File .\infra\scripts\login.ps1
#
#  당신이 하는 것     : 루트 액세스 키 두 줄 입력
#  스크립트가 하는 것 : IAM 사용자 anasudal-deploy + 정책 2개 생성
#                       -> 새 키를 anasudal 프로필에 자동 등록
#                       -> 루트 키 정리 -> 권한/계정 점검
#
#  키를 복사해 어디에 붙여넣을 필요가 없습니다. 시크릿은 화면에 찍지 않습니다.
#  (Linux/CloudShell 에서는 같은 폴더의 login.sh 를 쓰세요)
# =============================================================================

$ErrorActionPreference = 'Continue'

$BOOT     = 'root-bootstrap'   # 루트 키를 잠깐 담는 프로필. 끝나면 비운다
$TARGET   = 'anasudal'         # 앞으로 계속 쓸 프로필
$REGION   = 'ap-northeast-2'
$USERNAME = 'anasudal-deploy'
$PROJECT  = 'anasudal'
$IamDir   = Join-Path (Split-Path $PSScriptRoot -Parent) 'iam'

function Say  ($t) { Write-Host ''; Write-Host $t -ForegroundColor Cyan }
function Ok   ($t) { Write-Host "  $t" -ForegroundColor Green }
function Warn ($t) { Write-Host "  $t" -ForegroundColor Yellow }
function Bad  ($t) { Write-Host "  $t" -ForegroundColor Red }
function Info ($t) { Write-Host "  $t" }

if (-not (Get-Command aws -ErrorAction SilentlyContinue)) {
  Bad 'AWS CLI 를 찾을 수 없습니다.'
  Info 'https://aws.amazon.com/cli/ 에서 설치한 뒤 PowerShell 을 새로 여세요.'
  exit 1
}
foreach ($f in @('anasudal-deploy-core.json', 'anasudal-deploy-infra.json')) {
  if (-not (Test-Path (Join-Path $IamDir $f))) {
    Bad "정책 파일이 없습니다: $(Join-Path $IamDir $f)"
    exit 1
  }
}

# -- 1. 루트 로그인 -----------------------------------------------------------
Say '1/5  루트 로그인'

$CallerArn = & aws sts get-caller-identity --profile $BOOT --query Arn --output text 2>$null
if ($LASTEXITCODE -eq 0 -and $CallerArn) {
  Info '이미 로그인돼 있습니다. 넘어갑니다.'
} else {
  Write-Host @'

  루트 액세스 키가 필요합니다. 아직 없으면 이렇게 만드세요 (콘솔, 1분):

    AWS 콘솔 우측 상단 계정 이름
      -> 보안 자격 증명 (Security credentials)
      -> 아래로 스크롤 -> 액세스 키 -> 액세스 키 만들기
      -> 경고 체크박스 확인 -> 만들기

  키와 시크릿이 그 화면에서만 보입니다. 아래에 그대로 붙여넣으세요.
  (시크릿은 입력해도 화면에 안 보일 수 있습니다. 리전/출력형식은 Enter)

'@
  aws configure --profile $BOOT
  $null = & aws configure set region $REGION --profile $BOOT
  $null = & aws configure set output json    --profile $BOOT

  $CallerArn = & aws sts get-caller-identity --profile $BOOT --query Arn --output text 2>$null
  if ($LASTEXITCODE -ne 0 -or -not $CallerArn) {
    Bad '인증 실패 - 키를 잘못 붙여넣었을 수 있습니다.'
    Info '다시 실행해 보세요. 방금 만든 키가 맞는지도 확인하세요.'
    exit 1
  }
}

$Account = & aws sts get-caller-identity --profile $BOOT --query Account --output text
Ok "계정 $Account"
Ok "주체 $CallerArn"
$IsRoot = $CallerArn.EndsWith(':root')
if ($IsRoot) { Warn '루트로 실행 중입니다. 4단계에서 이 키를 정리합니다.' }

# -- 2. 전용 IAM 사용자 -------------------------------------------------------
Say '2/5  전용 IAM 사용자 만들기'

function Set-ProjectPolicy ($Name, $SrcFile) {
  # 정책 본문 경로에 한글이 섞이면 CLI 가 읽지 못할 수 있어 TEMP 로 복사한다
  $tmp = Join-Path $env:TEMP "$Name.json"
  Copy-Item $SrcFile $tmp -Force
  $arn = "arn:aws:iam::${Account}:policy/$Name"

  $null = & aws iam get-policy --policy-arn $arn --profile $BOOT 2>$null
  if ($LASTEXITCODE -eq 0) {
    # 정책 버전은 5개까지 - 오래된 비기본 버전을 먼저 지운다
    $vers = & aws iam list-policy-versions --policy-arn $arn --profile $BOOT `
              --query 'Versions[?IsDefaultVersion==`false`].VersionId' --output text 2>$null
    if ($LASTEXITCODE -eq 0 -and $vers) {
      $list = @($vers -split '\s+' | Where-Object { $_ })
      if ($list.Count -ge 4) {
        foreach ($v in $list[3..($list.Count - 1)]) {
          $null = & aws iam delete-policy-version --policy-arn $arn --version-id $v --profile $BOOT 2>$null
        }
      }
    }
    $null = & aws iam create-policy-version --policy-arn $arn `
              --policy-document "file://$tmp" --set-as-default --profile $BOOT
    if ($LASTEXITCODE -ne 0) { Bad "정책 갱신 실패: $Name"; exit 1 }
    Ok "정책 갱신: $Name"
  } else {
    $null = & aws iam create-policy --policy-name $Name `
              --policy-document "file://$tmp" --tags "Key=Project,Value=$PROJECT" --profile $BOOT
    if ($LASTEXITCODE -ne 0) { Bad "정책 생성 실패: $Name"; exit 1 }
    Ok "정책 생성: $Name"
  }
  Remove-Item $tmp -Force -ErrorAction SilentlyContinue
  return $arn
}

$CoreArn  = Set-ProjectPolicy 'anasudal-deploy-core'  (Join-Path $IamDir 'anasudal-deploy-core.json')
$InfraArn = Set-ProjectPolicy 'anasudal-deploy-infra' (Join-Path $IamDir 'anasudal-deploy-infra.json')

$null = & aws iam get-user --user-name $USERNAME --profile $BOOT 2>$null
if ($LASTEXITCODE -eq 0) {
  Info "사용자 있음: $USERNAME"
} else {
  $null = & aws iam create-user --user-name $USERNAME --tags "Key=Project,Value=$PROJECT" --profile $BOOT
  if ($LASTEXITCODE -ne 0) { Bad '사용자 생성 실패'; exit 1 }
  Ok "사용자 생성: $USERNAME"
}
$null = & aws iam attach-user-policy --user-name $USERNAME --policy-arn $CoreArn  --profile $BOOT
$null = & aws iam attach-user-policy --user-name $USERNAME --policy-arn $InfraArn --profile $BOOT
Ok '정책 연결 완료'

# 액세스 키는 사용자당 2개까지. 꽉 찼으면 가장 오래된 것을 지운다
$cnt = & aws iam list-access-keys --user-name $USERNAME --profile $BOOT `
         --query 'length(AccessKeyMetadata)' --output text 2>$null
if ($LASTEXITCODE -eq 0 -and [int]$cnt -ge 2) {
  $old = & aws iam list-access-keys --user-name $USERNAME --profile $BOOT `
           --query 'sort_by(AccessKeyMetadata,&CreateDate)[0].AccessKeyId' --output text
  $null = & aws iam delete-access-key --user-name $USERNAME --access-key-id $old --profile $BOOT
  Warn "오래된 키 삭제: $old"
}

$pair = & aws iam create-access-key --user-name $USERNAME --profile $BOOT `
          --query 'AccessKey.[AccessKeyId,SecretAccessKey]' --output text
if ($LASTEXITCODE -ne 0) { Bad '액세스 키 발급 실패'; exit 1 }
$parts     = @($pair -split '\s+' | Where-Object { $_ })
$NewId     = $parts[0]
$NewSecret = $parts[1]
Ok "액세스 키 발급: $NewId  (시크릿은 화면에 남기지 않습니다)"

# -- 3. 프로필 등록 -----------------------------------------------------------
Say '3/5  anasudal 프로필에 등록'
$null = & aws configure set aws_access_key_id     $NewId     --profile $TARGET
$null = & aws configure set aws_secret_access_key $NewSecret --profile $TARGET
$null = & aws configure set region $REGION --profile $TARGET
$null = & aws configure set output json    --profile $TARGET
Remove-Variable NewSecret -ErrorAction SilentlyContinue
Ok "$env:USERPROFILE\.aws\credentials 의 [$TARGET] 에 저장했습니다."

# 새 키는 AWS 내부에 퍼지는 데 몇 초 걸린다
Write-Host -NoNewline '  새 키 활성화를 기다리는 중'
$Ready = $false
for ($i = 0; $i -lt 12; $i++) {
  $null = & aws sts get-caller-identity --profile $TARGET 2>$null
  if ($LASTEXITCODE -eq 0) { $Ready = $true; break }
  Write-Host -NoNewline '.'
  Start-Sleep -Seconds 3
}
Write-Host ''
if ($Ready) {
  Ok (& aws sts get-caller-identity --profile $TARGET --query Arn --output text)
} else {
  Warn '아직 응답이 없습니다. 1분쯤 뒤 확인해 보세요:'
  Info "  aws sts get-caller-identity --profile $TARGET"
}

# -- 4. 루트 키 정리 ----------------------------------------------------------
Say '4/5  루트 키 정리'
if ($IsRoot -and $Ready) {
  Info '루트 키는 계정 전체를 열 수 있어서, 이제 없애는 게 안전합니다.'
  Info '(새 키가 동작하는 것을 위에서 확인했습니다)'
  $ans = Read-Host '  지금 삭제할까요? 삭제하려면 yes 입력'
  if ($ans -eq 'yes') {
    $rk = & aws iam list-access-keys --profile $BOOT `
            --query 'AccessKeyMetadata[0].AccessKeyId' --output text 2>$null
    if ($LASTEXITCODE -eq 0 -and $rk -and $rk -ne 'None') {
      $null = & aws iam delete-access-key --access-key-id $rk --profile $BOOT 2>$null
      if ($LASTEXITCODE -eq 0) {
        Ok "루트 키 삭제: $rk"
      } else {
        Warn 'CLI 로 지우지 못했습니다. 콘솔에서 지워주세요:'
        Info '  계정 이름 -> 보안 자격 증명 -> 액세스 키 -> 삭제'
      }
    } else {
      Warn '루트 키 목록을 못 읽었습니다. 콘솔에서 직접 지워주세요.'
    }
  } else {
    Warn '건너뜁니다. 나중에 콘솔에서 꼭 지우세요 (계정 이름 -> 보안 자격 증명).'
  }
  $null = & aws configure set aws_access_key_id     '' --profile $BOOT 2>$null
  $null = & aws configure set aws_secret_access_key '' --profile $BOOT 2>$null
  Ok "이 PC 의 [$BOOT] 프로필에서도 키를 비웠습니다."
} else {
  Info '루트가 아니거나 확인이 끝나지 않아 건너뜁니다.'
}

# -- 5. 점검 ------------------------------------------------------------------
Say '5/5  권한 / 계정 점검'
$env:AWS_PROFILE = $TARGET

function Probe ($Label, [scriptblock]$Cmd) {
  $null = & $Cmd 2>$null
  if ($LASTEXITCODE -eq 0) { Write-Host "  [O] $Label" -ForegroundColor Green }
  else                     { Write-Host "  [X] $Label" -ForegroundColor Red }
}
Probe 'EC2  조회'        { aws ec2 describe-vpcs --max-items 1 }
Probe 'ECR  조회'        { aws ecr describe-repositories --max-items 1 }
Probe 'ECS  조회'        { aws ecs list-clusters --max-items 1 }
Probe 'RDS  조회'        { aws rds describe-db-instances --max-items 1 }
Probe 'ElastiCache 조회' { aws elasticache describe-cache-clusters --max-items 1 }
Probe 'SSM  파라미터'    { aws ssm describe-parameters --max-items 1 }
Probe 'IAM  역할 조회'   { aws iam list-roles --max-items 1 }
Probe 'CloudWatch 로그'  { aws logs describe-log-groups --max-items 1 }

Write-Host ''
Write-Host '-- 계정에 이미 있는 것 (기존 프로젝트 확인용) --'
Write-Host '  VPC:'
aws ec2 describe-vpcs --query 'Vpcs[].{id:VpcId,cidr:CidrBlock,default:IsDefault,name:Tags[?Key==`Name`]|[0].Value,project:Tags[?Key==`Project`]|[0].Value}' --output table
Write-Host '  ECS 클러스터:'
aws ecs list-clusters --query 'clusterArns' --output text
Write-Host '  RDS:'
aws rds describe-db-instances --query 'DBInstances[].DBInstanceIdentifier' --output text

Say '끝났습니다'
Write-Host @"
  앞으로는 이 프로필을 씁니다:

      `$env:AWS_PROFILE = '$TARGET'

  위 [O]/[X] 목록과 VPC/ECS/RDS 결과를 Claude 에게 그대로 붙여넣어 주세요.
  기존 프로젝트와 겹치는 게 없는지 확인한 뒤 인프라 생성으로 넘어갑니다.
"@
