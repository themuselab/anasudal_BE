# =============================================================================
#  기존 프로젝트(syak) 리소스에 Project=syak 태그를 붙인다.
#
#    powershell -ExecutionPolicy Bypass -File .\infra\iam\tag-syak.ps1 -KeyFile <루트키.csv>
#
#  왜 루트가 필요한가
#    anasudal-deploy 사용자는 syak 리소스를 건드릴 수 없도록 막아뒀다(의도된 설계).
#    그래서 이 한 번의 태깅만 루트로 한다. 끝나면 자격 증명을 메모리에서 지운다.
#
#  태그를 붙여도 분리는 약해지지 않는다
#    Deny 조건은 "Project != anasudal" 이다. syak != anasudal 이므로 보호는 그대로다.
#    오히려 태그가 없어 암묵적으로 걸리던 것이 명시적으로 걸리게 되어 더 분명해진다.
#    비용 할당(Cost Explorer)에서 두 프로젝트를 나눠 볼 수 있게 되는 것이 실질 이득이다.
# =============================================================================

param(
  [Parameter(Mandatory = $true)][string]$KeyFile,
  [string]$Region  = 'ap-northeast-2',
  [string]$TagKey  = 'Project',
  [string]$TagVal  = 'syak',
  [switch]$WhatIf          # 실제로 붙이지 않고 대상만 보여준다
)

$ErrorActionPreference = 'Continue'

function Say  ($t) { Write-Host ''; Write-Host $t -ForegroundColor Cyan }
function Ok   ($t) { Write-Host "  $t" -ForegroundColor Green }
function Warn ($t) { Write-Host "  $t" -ForegroundColor Yellow }
function Bad  ($t) { Write-Host "  $t" -ForegroundColor Red }
function Info ($t) { Write-Host "  $t" }

if (-not (Test-Path $KeyFile)) { Bad "키 파일이 없습니다: $KeyFile"; exit 1 }

# 키 파일에서 자격 증명을 읽어 이 프로세스에만 넣는다 (디스크·프로필에 남기지 않음)
$raw = Get-Content $KeyFile -Raw
$mId  = [regex]::Match($raw, '(?<![A-Z0-9])((?:AKIA|ASIA)[A-Z0-9]{16})(?![A-Z0-9])')
$mSec = [regex]::Match($raw, '(?<![A-Za-z0-9+/=])([A-Za-z0-9+/=]{40})(?![A-Za-z0-9+/=])')
if (-not ($mId.Success -and $mSec.Success)) { Bad '키 파일에서 자격 증명을 찾지 못했습니다.'; exit 1 }

$env:AWS_ACCESS_KEY_ID     = $mId.Groups[1].Value
$env:AWS_SECRET_ACCESS_KEY = $mSec.Groups[1].Value
$env:AWS_DEFAULT_REGION    = $Region
Remove-Item Env:AWS_PROFILE -ErrorAction SilentlyContinue   # 프로필이 끼어들지 않게

try {
  Say '0. 자격 증명 확인'
  $arn = & aws sts get-caller-identity --query Arn --output text 2>$null
  if ($LASTEXITCODE -ne 0) { Bad '인증 실패 - 키 파일을 확인하세요.'; exit 1 }
  $acct = & aws sts get-caller-identity --query Account --output text
  Ok "$arn  (계정 $acct)"

  # -- 대상 수집 : 이름/식별자가 syak 인 것만 모은다 ------------------------
  Say '1. 태그를 붙일 대상 찾기'

  $ec2Ids = New-Object System.Collections.Generic.List[string]
  $arns   = New-Object System.Collections.Generic.List[string]

  # EC2 인스턴스 - Name 태그가 syak* 인 것
  $inst = & aws ec2 describe-instances `
            --filters 'Name=tag:Name,Values=syak*' 'Name=instance-state-name,Values=pending,running,stopping,stopped' `
            --query 'Reservations[].Instances[].InstanceId' --output text
  foreach ($x in @($inst -split '\s+' | Where-Object { $_ })) { $ec2Ids.Add($x) }

  # 보안 그룹 - 이름이 syak* 인 것
  $sgs = & aws ec2 describe-security-groups `
           --filters 'Name=group-name,Values=syak*' `
           --query 'SecurityGroups[].GroupId' --output text
  foreach ($x in @($sgs -split '\s+' | Where-Object { $_ })) { $ec2Ids.Add($x) }

  # syak 인스턴스가 들어 있는 VPC 와 그 서브넷
  #   기본 VPC 지만 지금 이 계정에서 유일한 워크로드가 syak 이므로 같이 표시해 둔다.
  #   (다른 용도로 쓰게 되면 이 태그만 바꾸면 된다)
  if ($ec2Ids.Count -gt 0) {
    $vpc = & aws ec2 describe-instances --instance-ids $ec2Ids[0] `
             --query 'Reservations[0].Instances[0].VpcId' --output text
    if ($LASTEXITCODE -eq 0 -and $vpc -and $vpc -ne 'None') {
      $ec2Ids.Add($vpc)
      $subs = & aws ec2 describe-subnets --filters "Name=vpc-id,Values=$vpc" `
                --query 'Subnets[].SubnetId' --output text
      foreach ($x in @($subs -split '\s+' | Where-Object { $_ })) { $ec2Ids.Add($x) }
    }
  }

  # RDS - 식별자가 syak* 인 것
  $dbs = & aws rds describe-db-instances `
           --query 'DBInstances[?starts_with(DBInstanceIdentifier,`syak`)].DBInstanceArn' --output text
  foreach ($x in @($dbs -split '\s+' | Where-Object { $_ })) { $arns.Add($x) }

  # ECS 클러스터 + 그 안의 서비스
  $clusters = & aws ecs list-clusters --query 'clusterArns' --output text
  foreach ($c in @($clusters -split '\s+' | Where-Object { $_ -match '/syak' })) {
    $arns.Add($c)
    $svcs = & aws ecs list-services --cluster $c --query 'serviceArns' --output text
    foreach ($s in @($svcs -split '\s+' | Where-Object { $_ })) { $arns.Add($s) }
  }

  # ECR - 이름이 syak* 인 리포지토리
  $repos = & aws ecr describe-repositories `
             --query 'repositories[?starts_with(repositoryName,`syak`)].repositoryArn' --output text
  foreach ($x in @($repos -split '\s+' | Where-Object { $_ })) { $arns.Add($x) }

  Info "EC2 계열 $($ec2Ids.Count)개 : $($ec2Ids -join ', ')"
  foreach ($a in $arns) { Info "그 외        : $a" }

  if ($ec2Ids.Count -eq 0 -and $arns.Count -eq 0) { Warn '대상이 없습니다.'; exit 0 }
  if ($WhatIf) { Warn '-WhatIf 지정 — 실제로 붙이지 않고 끝냅니다.'; exit 0 }

  # -- 태그 붙이기 -----------------------------------------------------------
  Say "2. $TagKey=$TagVal 태그 붙이기"
  $fail = 0

  if ($ec2Ids.Count -gt 0) {
    $null = & aws ec2 create-tags --resources $ec2Ids --tags "Key=$TagKey,Value=$TagVal"
    if ($LASTEXITCODE -eq 0) { Ok "EC2/VPC/서브넷/보안그룹 $($ec2Ids.Count)개" }
    else { Bad "EC2 계열 실패"; $fail++ }
  }

  foreach ($a in $arns) {
    $svc = ($a -split ':')[2]
    switch ($svc) {
      'rds' { $null = & aws rds add-tags-to-resource --resource-name $a --tags "Key=$TagKey,Value=$TagVal" }
      'ecs' { $null = & aws ecs tag-resource --resource-arn $a --tags "key=$TagKey,value=$TagVal" }
      'ecr' { $null = & aws ecr tag-resource  --resource-arn $a --tags "Key=$TagKey,Value=$TagVal" }
      default { Warn "어떻게 태그할지 모르는 리소스: $a"; continue }
    }
    if ($LASTEXITCODE -eq 0) { Ok (($a -split '/')[-1] + "  ($svc)") }
    else { Bad "실패: $a"; $fail++ }
  }

  # -- 확인 -------------------------------------------------------------------
  Say '3. 확인'
  aws ec2 describe-instances --instance-ids $ec2Ids[0] `
    --query 'Reservations[0].Instances[0].Tags' --output table 2>$null

  Write-Host ''
  if ($fail -eq 0) { Ok '전부 성공했습니다.' } else { Bad "$fail 건 실패 — 위 로그를 확인하세요." }
}
finally {
  # 루트 자격 증명을 이 프로세스에서 지운다
  Remove-Item Env:AWS_ACCESS_KEY_ID, Env:AWS_SECRET_ACCESS_KEY, Env:AWS_DEFAULT_REGION -ErrorAction SilentlyContinue
}
