#!/bin/bash
# data.go.kr fileData 다운로드 (로그인 불필요)
UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120"
id=$1; name=$2
html=$(curl -s -m 40 -A "$UA" "https://www.data.go.kr/data/$id/fileData.do")
atch=$(echo "$html" | grep -oE 'atchFileId=FILE_[0-9]+' | head -1 | cut -d= -f2)
if [ -z "$atch" ]; then echo "  [$name] 다운로드 링크 없음"; return 2>/dev/null || exit 0; fi
curl -s -m 60 -L -A "$UA" -H "Referer: https://www.data.go.kr/data/$id/fileData.do" \
  "https://www.data.go.kr/cmm/cmm/fileDownload.do?atchFileId=$atch&fileDetailSn=1&insertDataPrcus=N" \
  -o "data/raw/ds_$name" -w "  [$name] HTTP:%{http_code} SIZE:%{size_download}\n"
