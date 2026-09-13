# -*- coding: utf-8 -*-
"""사회보장정보원 API 구간 수집 (이어받기). 사용: python scripts/fetch_ssis_chunk.py <시작페이지> <페이지수>"""
import re, io, os, csv, subprocess, sys, time
BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
D = lambda *p: os.path.join(BASE, *p)
KEY = ("joXNJdXqmurTlcDnLFfiRLBAvpUwjHJ8KLufGpyx1f%2BahBiebi%2FEW0VvEPJCP%2FBmIN"
       "BoEUedOnUvJ9ca57pE5A%3D%3D")
URL = "https://api.socialservice.or.kr:444/api/service/provider/providerList"
ROWS = 300
start, cnt = int(sys.argv[1]), int(sys.argv[2])
FIELDS = ["providerName", "serviceTypeName", "sidoName", "signguName", "telNumber", "email",
          "loadAddress", "loadAddressDetail"]
out = D("data", "ssis_dev_rehab.csv")
seen = set()
old = []
if os.path.exists(out):
    old = list(csv.DictReader(io.open(out, encoding="utf-8-sig")))
    seen = {(r["providerName"], r["telNumber"]) for r in old}
def f(it, t):
    m = re.search(r"<%s>(.*?)</%s>" % (t, t), it, re.S)
    return m.group(1).strip() if m else ""
new = []
for pg in range(start, start + cnt):
    p = subprocess.run(["curl", "-s", "-m", "45", "-k",
                        "%s?serviceKey=%s&pageNo=%d&numOfRows=%d" % (URL, KEY, pg, ROWS)],
                       capture_output=True)
    x = p.stdout.decode("utf-8", "replace")
    for it in re.findall(r"<item>(.*?)</item>", x, re.S):
        st = f(it, "serviceTypeName")
        if "장애아동" in st or "발달재활" in st or "언어발달" in st:
            rec = {k: f(it, k) for k in FIELDS}
            key = (rec["providerName"], rec["telNumber"])
            if key not in seen:
                seen.add(key); new.append(rec)
with io.open(out, "w", encoding="utf-8-sig", newline="") as fp:
    w = csv.DictWriter(fp, fieldnames=FIELDS); w.writeheader(); w.writerows(old + new)
print("페이지 %d~%d → 신규 %d건 (누적 %d건)" % (start, start + cnt - 1, len(new), len(old) + len(new)))
