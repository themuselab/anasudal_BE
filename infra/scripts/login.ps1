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
#  키 입력 방법은 세 가지. 편한 것을 고르면 됩니다 (자동으로 순서대로 시도).
#    1) 콘솔에서 받은 .csv 파일  <- 가장 쉬움. 타이핑도 붙여넣기도 없음
#    2) 메모장에 붙여넣기        <- 터미널 붙여넣기가 안 될 때
#    3) 터미널에 직접 입력
#
#  시크릿은 어느 경우에도 화면에 찍지 않습니다.
#  (Linux/CloudShell 에서는 같은 폴더의 login.sh 를 쓰세요)
# =============================================================================

param(
  # 콘솔에서 받은 액세스 키 파일 경로를 직접 지정할 때 사용
  [string]$KeyFile
)

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

# -- 키 읽기 도우미 -----------------------------------------------------------
# 형식을 가리지 않는다. csv / 메모장 메모 / 아무 텍스트에서나 정규식으로 찾아낸다.
#   액세스 키 ID : AKIA/ASIA + 영숫자 16자
#   시크릿       : base64 문자 40자
function Get-AwsKeyFromText ($text) {
  if (-not $text) { return $null }
  $id = $null; $sec = $null

  # (1) key = value 표기  (메모장 템플릿, 환경변수, ~/.aws/credentials 형식)
  $m = [regex]::Match($text, '(?im)^\s*(?:aws[_ ]?)?access[_ ]?key[_ ]?id\s*[=:]\s*["'']?([A-Z0-9]{16,128})')
  if ($m.Success) { $id = $m.Groups[1].Value }
  $m = [regex]::Match($text, '(?im)^\s*(?:aws[_ ]?)?secret[_ ]?access[_ ]?key\s*[=:]\s*["'']?([A-Za-z0-9+/=]{30,128})')
  if ($m.Success) { $sec = $m.Groups[1].Value }

  # (2) 콘솔에서 받은 .csv — 헤더 이름으로 열을 찾는다.
  #     IAM 사용자 csv 에는 비밀번호 열이 섞여 있어서, 위치로 찍지 않고 이름으로 찾아야 한다.
  if (-not ($id -and $sec)) {
    try {
      foreach ($r in @($text | ConvertFrom-Csv)) {
        foreach ($p in $r.PSObject.Properties) {
          $n = ($p.Name -replace '[^A-Za-z]', '').ToLower()
          if ($n -eq 'accesskeyid'     -and $p.Value) { $id  = ([string]$p.Value).Trim() }
          if ($n -eq 'secretaccesskey' -and $p.Value) { $sec = ([string]$p.Value).Trim() }
        }
        if ($id -and $sec) { break }
      }
    } catch { }
  }

  # (3) 그래도 못 찾으면 생김새로 찾는다 (아무 텍스트나 통째로 붙여넣은 경우)
  if (-not $id) {
    $m = [regex]::Match($text, '(?<![A-Z0-9])((?:AKIA|ASIA)[A-Z0-9]{16})(?![A-Z0-9])')
    if ($m.Success) { $id = $m.Groups[1].Value }
  }
  if (-not $sec) {
    $m = [regex]::Match($text, '(?<![A-Za-z0-9+/=])([A-Za-z0-9+/=]{40})(?![A-Za-z0-9+/=])')
    if ($m.Success) { $sec = $m.Groups[1].Value }
  }

  if ($id -and $sec -and $id -match '^(AKIA|ASIA)[A-Z0-9]{16}$') {
    return [pscustomobject]@{ Id = $id; Secret = $sec }
  }
  return $null
}

# 콘솔에서 받은 키 파일을 흔히 저장되는 위치에서 찾는다
function Find-KeyFile {
  $dirs = @("$env:USERPROFILE\Downloads", "$env:USERPROFILE\Desktop", (Get-Location).Path)
  $pats = @('rootkey*.csv', '*accessKeys*.csv', '*credentials*.csv', '*access*key*.csv')
  $hits = @()
  foreach ($d in $dirs) {
    if (-not (Test-Path $d)) { continue }
    foreach ($p in $pats) {
      $hits += Get-ChildItem -Path $d -Filter $p -File -ErrorAction SilentlyContinue
    }
  }
  return @($hits | Sort-Object FullName -Unique |
                   Sort-Object LastWriteTime -Descending |
                   Select-Object -First 5)
}

# 터미널 붙여넣기가 안 될 때: 메모장에 붙여넣게 한다
function Read-KeyViaNotepad {
  $tmp = Join-Path $env:TEMP ('anasudal-key-' + [guid]::NewGuid().ToString('N').Substring(0, 8) + '.txt')
  @(
    '이 파일에 액세스 키를 붙여넣고 저장(Ctrl+S) 한 뒤 메모장을 닫으세요.',
    '아래 두 줄의 = 뒤에 값을 채워도 되고, 콘솔에서 복사한 내용을 통째로',
    '아무 데나 붙여넣어도 알아서 찾아냅니다.',
    '',
    'AWS_ACCESS_KEY_ID=',
    'AWS_SECRET_ACCESS_KEY='
  ) | Set-Content -Path $tmp -Encoding utf8
  Info '메모장이 열립니다. 키를 붙여넣고 저장한 뒤 창을 닫으세요.'
  Start-Process notepad.exe -ArgumentList $tmp -Wait
  $k = Get-AwsKeyFromText (Get-Content $tmp -Raw)
  Remove-Item $tmp -Force -ErrorAction SilentlyContinue
  return $k
}

# -- 1. 루트 로그인 -----------------------------------------------------------
Say '1/5  루트 로그인'

$CallerArn = & aws sts get-caller-identity --profile $BOOT --query Arn --output text 2>$null
if ($LASTEXITCODE -eq 0 -and $CallerArn) {
  Info '이미 로그인돼 있습니다. 넘어갑니다.'
} else {

  $key = $null

  # (a) -KeyFile 로 직접 지정한 경우
  if ($KeyFile) {
    if (-not (Test-Path $KeyFile)) { Bad "파일이 없습니다: $KeyFile"; exit 1 }
    $key = Get-AwsKeyFromText (Get-Content $KeyFile -Raw)
    if (-not $key) { Bad "이 파일에서 액세스 키를 찾지 못했습니다: $KeyFile"; exit 1 }
    Ok "키 파일에서 읽었습니다: $(Split-Path $KeyFile -Leaf)"
  }

  # (b) 메뉴로 고르기
  if (-not $key) {
    Write-Host @'

  루트 액세스 키가 필요합니다. 아직 없으면 콘솔에서 만드세요 (1분):

    AWS 콘솔 우측 상단 계정 이름
      -> 보안 자격 증명 (Security credentials)
      -> 아래로 스크롤 -> 액세스 키 -> 액세스 키 만들기
      -> 경고 체크박스 확인 -> 만들기
      -> [ .csv 파일 다운로드 ] 버튼을 누르세요  <<< 이게 제일 편합니다

'@
    $tries = 0
    while (-not $key) {
      $tries++
      if ($tries -gt 8) {
        Bad '입력을 받지 못했습니다. 아무것도 만들지 않고 종료합니다.'
        Info '키 파일이 있다면 경로를 직접 주고 다시 실행하세요:'
        Info '  powershell -ExecutionPolicy Bypass -File .\infra\scripts\login.ps1 -KeyFile "C:\경로\rootkey.csv"'
        exit 1
      }
      $files = Find-KeyFile
      Write-Host '  키를 어떻게 넣을까요?'
      $i = 0
      foreach ($f in $files) {
        $i++
        $mins = ((Get-Date) - $f.LastWriteTime).TotalMinutes
        if     ($mins -lt 60)   { $when = "{0}분 전" -f [int]$mins }
        elseif ($mins -lt 1440) { $when = "{0}시간 전" -f [int]($mins / 60) }
        else                    { $when = $f.LastWriteTime.ToString('yyyy-MM-dd') }
        $line = "    [{0}] {1}   ({2}, {3})" -f $i, $f.Name, (Split-Path $f.DirectoryName -Leaf), $when
        if ($mins -gt 1440) {
          Write-Host ($line + '  <- 오래된 파일. 방금 만든 키가 맞는지 확인하세요') -ForegroundColor DarkGray
        } else {
          Write-Host $line
        }
      }
      if ($files.Count -eq 0) {
        Write-Host '    (다운로드 폴더에서 키 파일(.csv)을 찾지 못했습니다)'
      }
      Write-Host '    [F] 다른 위치의 키 파일 경로를 입력'
      Write-Host '    [N] 메모장에 붙여넣기   <- 터미널 붙여넣기가 안 될 때'
      Write-Host '    [T] 터미널에 직접 입력'
      Write-Host '    [Q] 그만두기'
      $sel = Read-Host '  선택'

      if ($sel -match '^[0-9]+$' -and [int]$sel -ge 1 -and [int]$sel -le $files.Count) {
        $pick = $files[[int]$sel - 1]
        $key = Get-AwsKeyFromText (Get-Content $pick.FullName -Raw)
        if ($key) { Ok "읽었습니다: $($pick.Name)" }
        else      { Warn "$($pick.Name) 에서 액세스 키를 찾지 못했습니다. 다시 고르세요." }
      }
      elseif ($sel -eq 'F' -or $sel -eq 'f') {
        $path = (Read-Host '  파일 경로').Trim('"', ' ')
        if (Test-Path $path) {
          $key = Get-AwsKeyFromText (Get-Content $path -Raw)
          if (-not $key) { Warn '그 파일에서 액세스 키를 찾지 못했습니다.' }
        } else { Warn '파일이 없습니다.' }
      }
      elseif ($sel -eq 'N' -or $sel -eq 'n') {
        $key = Read-KeyViaNotepad
        if (-not $key) { Warn '메모장 내용에서 액세스 키를 찾지 못했습니다.' }
      }
      elseif ($sel -eq 'T' -or $sel -eq 't') {
        Write-Host @'

  붙여넣기가 안 되면:
    · 마우스 오른쪽 버튼 클릭 = 붙여넣기 (Windows PowerShell 기본 동작)
    · 또는 Ctrl+Shift+V
    · 창 제목 표시줄 오른쪽 클릭 -> 속성 -> "Ctrl+Shift+C/V를 복사/붙여넣기로 사용" 체크
  (리전과 출력 형식은 그냥 Enter)

'@
        aws configure --profile $BOOT
        $null = & aws configure set region $REGION --profile $BOOT
        $null = & aws configure set output json    --profile $BOOT
        $probe = & aws sts get-caller-identity --profile $BOOT --query Arn --output text 2>$null
        if ($LASTEXITCODE -eq 0 -and $probe) { break }
        Warn '입력한 키로 인증되지 않았습니다. 다시 고르세요.'
      }
      elseif ($sel -eq 'Q' -or $sel -eq 'q') {
        Info '그만둡니다. 아무것도 만들지 않았습니다.'
        exit 1
      }
      else { Warn '목록에 있는 번호나 글자를 입력하세요.' }
      Write-Host ''
    }
  }

  if ($key) {
    $null = & aws configure set aws_access_key_id     $key.Id     --profile $BOOT
    $null = & aws configure set aws_secret_access_key $key.Secret --profile $BOOT
    $null = & aws configure set region $REGION --profile $BOOT
    $null = & aws configure set output json    --profile $BOOT
    $key = $null
    Remove-Variable key -ErrorAction SilentlyContinue
  }

  $CallerArn = & aws sts get-caller-identity --profile $BOOT --query Arn --output text 2>$null
  if ($LASTEXITCODE -ne 0 -or -not $CallerArn) {
    Bad '인증 실패 - 키가 유효하지 않습니다.'
    Info '콘솔에서 방금 만든 키가 맞는지, 비활성 상태는 아닌지 확인하고 다시 실행하세요.'
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
