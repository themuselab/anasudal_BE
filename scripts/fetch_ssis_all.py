# -*- coding: utf-8 -*-
"""한국사회보장정보원 사회서비스 제공기관 API 전량 수집 -> 발달재활(장애아동가족지원)만 추출"""
import re, io, os, csv, subprocess, time, collections

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
D = lambda *p: os.path.join(BASE, *p)
KEY = ("joXNJdXqmurTlcDnLFfiRLBAvpUwjHJ8KLufGpyx1f%2BahBiebi%2FEW0VvEPJCP%2FBmIN"
       "BoEUedOnUvJ9ca57pE5A%3D%3D")
URL = "https://api.socialservice.or.kr:444/api/service/provider/providerList"
ROWS = 300

def get(page):
    u = "%s?serviceKey=%s&pageNo=%d&numOfRows=%d" % (URL, KEY, page, ROWS)
    for _ in range(3):
        p = subprocess.run(["curl", "-s", "-m", "60", "-k", u], capture_output=True)
        x = p.stdout.decode("utf-8", "replace")
        if "<item>" in x or "<totalCount>" in x:
            return x
        time.sleep(2)
    return ""

def f(it, tag):
    m = re.search(r"<%s>(.*?)</%s>" % (tag, tag), it, re.S)
    return m.group(1).strip() if m else ""

first = get(1)
total = int(re.search(r"<totalCount>(\d+)</totalCount>", first).group(1))
pages = (total + ROWS - 1) // ROWS
print("총 %d건 / %d페이지" % (total, pages), flush=True)

FIELDS = ["providerId", "providerName", "serviceName", "serviceTypeName",
          "sidoName", "signguName", "telNumber", "email",
          "loadAddress", "loadAddressDetail", "loadZip", "ownerName"]
rows, types = [], collections.Counter()
for pg in range(1, pages + 1):
    x = first if pg == 1 else get(pg)
    if not x:
        print("  page %d 실패" % pg, flush=True); continue
    for it in re.findall(r"<item>(.*?)</item>", x, re.S):
        st = f(it, "serviceTypeName")
        types[st] += 1
        if "장애아동" in st or "발달재활" in st or "언어발달" in st:
            rows.append({k: f(it, k) for k in FIELDS})
    if pg % 50 == 0:
        print("  %d/%d  발달재활 누적 %d" % (pg, pages, len(rows)), flush=True)

with io.open(D("data", "ssis_dev_rehab.csv"), "w", encoding="utf-8-sig", newline="") as fp:
    w = csv.DictWriter(fp, fieldnames=FIELDS); w.writeheader(); w.writerows(rows)
print("\nDONE 발달재활 관련 %d건" % len(rows))
print("사업구분 상위: %s" % types.most_common(8))
