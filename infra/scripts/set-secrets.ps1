# =============================================================================
#  Gemini API 키를 terraform.tfvars 에 넣는다 (메모장에 붙여넣는 방식)
#
#    powershell -ExecutionPolicy Bypass -File .\infra\scripts\set-secrets.ps1
#
#  메모장이 열립니다. 키를 붙여넣고 저장(Ctrl+S) 후 창을 닫으면 끝입니다.
#  터미널에 키를 치지 않으므로 명령 기록에도, 화면에도 남지 않습니다.
#  만들어지는 terraform.tfvars 는 .gitignore 에 있어 커밋되지 않습니다.
# =============================================================================

param(
  [string]$CorsOrigins = 'http://localhost:5173',
  [string]$GithubRepo  = 'themuselab/anasudal_BE'
)

$ErrorActionPreference = 'Continue'

function Ok   ($t) { Write-Host "  $t" -ForegroundColor Green }
function Warn ($t) { Write-Host "  $t" -ForegroundColor Yellow }
function Bad  ($t) { Write-Host "  $t" -ForegroundColor Red }
function Info ($t) { Write-Host "  $t" }

$TfDir   = Join-Path (Split-Path $PSScriptRoot -Parent) 'terraform'
$TfVars  = Join-Path $TfDir 'terraform.tfvars'
$Marker  = '여기에'

if (-not (Test-Path $TfDir)) { Bad "terraform 폴더가 없습니다: $TfDir"; exit 1 }

Write-Host ''
Write-Host 'Gemini API 키 입력' -ForegroundColor Cyan

# 이미 제대로 된 파일이 있으면 물어본다
if (Test-Path $TfVars) {
  $cur = Get-Content $TfVars -Raw
  if ($cur -notmatch $Marker -and $cur -match 'gemini_api_keys') {
    Warn 'terraform.tfvars 가 이미 있습니다.'
    $a = ''
    try { $a = Read-Host '  새로 입력할까요? (yes 면 덮어씀, 그냥 Enter 면 유지)' } catch { $a = '' }
    if ($a -ne 'yes') { Ok '기존 파일을 그대로 씁니다.'; exit 0 }
  }
}

$tmp = Join-Path $env:TEMP ('anasudal-tfvars-' + [guid]::NewGuid().ToString('N').Substring(0, 8) + '.txt')

@"
# ─────────────────────────────────────────────────────────────────────
#  Gemini API 키를 " " 안에 붙여넣고 저장(Ctrl+S) 후 이 창을 닫으세요.
#  '$Marker' 라는 글자가 남아 있으면 아직 안 채운 것으로 봅니다.
# ─────────────────────────────────────────────────────────────────────

# 답변·임베딩용. 여러 개 넣으면 하나가 한도에 걸렸을 때 다음 키로 넘어갑니다.
# 한 개만 있어도 됩니다:  gemini_api_keys = ["키하나"]
gemini_api_keys    = ["${Marker}_키1", "${Marker}_키2"]

# 질문 요약 전용 (답변 쿼터를 갉아먹지 않게 분리).
# 따로 없으면 위 키 중 하나를 그대로 적어도 됩니다.
gemini_summary_key = "${Marker}_요약용키"

# 프론트엔드 주소. 나중에 바꿔도 됩니다.
cors_origins       = "$CorsOrigins"
github_repo        = "$GithubRepo"
"@ | Set-Content -Path $tmp -Encoding utf8

Info '메모장이 열립니다. 키를 붙여넣고 저장한 뒤 창을 닫으세요.'
Start-Process notepad.exe -ArgumentList $tmp -Wait

$text = Get-Content $tmp -Raw
Remove-Item $tmp -Force -ErrorAction SilentlyContinue

# -- 검사 --------------------------------------------------------------------
if ($text -match [regex]::Escape($Marker)) {
  Bad '아직 채우지 않은 자리가 있습니다. 다시 실행해 주세요.'
  Info "('$Marker' 로 시작하는 값을 실제 키로 바꿔야 합니다)"
  exit 1
}

$keys = [regex]::Match($text, '(?m)^\s*gemini_api_keys\s*=\s*\[(.*?)\]')
$summ = [regex]::Match($text, '(?m)^\s*gemini_summary_key\s*=\s*"([^"]*)"')
if (-not $keys.Success) { Bad 'gemini_api_keys 줄을 찾지 못했습니다. 형식을 지켜 주세요.'; exit 1 }
if (-not $summ.Success) { Bad 'gemini_summary_key 줄을 찾지 못했습니다.'; exit 1 }

$keyList = @([regex]::Matches($keys.Groups[1].Value, '"([^"]*)"') |
             ForEach-Object { $_.Groups[1].Value.Trim() } |
             Where-Object { $_ })
if ($keyList.Count -eq 0) { Bad 'gemini_api_keys 가 비어 있습니다.'; exit 1 }
if (-not $summ.Groups[1].Value.Trim()) { Bad 'gemini_summary_key 가 비어 있습니다.'; exit 1 }

foreach ($k in $keyList) {
  if ($k.Length -lt 20) { Warn "키가 짧아 보입니다 ($($k.Length)자). 잘린 건 아닌지 확인하세요." }
}

# -- 저장 --------------------------------------------------------------------
# 주석을 걷어내고 값만 남긴다
$clean = ($text -split "`r?`n" | Where-Object { $_ -notmatch '^\s*#' -and $_.Trim() }) -join "`r`n"
[System.IO.File]::WriteAllText($TfVars, $clean + "`r`n", [System.Text.UTF8Encoding]::new($false))

Write-Host ''
Ok "저장했습니다: $TfVars"
Info "답변용 키 $($keyList.Count)개, 요약용 키 1개 (값은 표시하지 않습니다)"
Info '이 파일은 .gitignore 에 있어 커밋되지 않습니다.'
Write-Host ''
Write-Host '  이제 Claude 에게 "키 넣었어" 라고 알려주시면 apply 합니다.' -ForegroundColor Cyan
