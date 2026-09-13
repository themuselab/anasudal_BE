# -*- coding: utf-8 -*-
"""카카오 플레이스 상세에서 운영시간·홈페이지를 모은다.

⚠ 공개 API 가 아니다
  place-api.map.kakao.com 은 카카오맵 웹페이지가 내부적으로 쓰는 엔드포인트다.
  문서화돼 있지 않고, 카카오가 예고 없이 바꾸거나 막을 수 있으며, 약관상 권장되는
  방식도 아니다. 운영시간은 공식 REST API·공공데이터 어디에도 없어서 이 경로를 쓴다.
  (이 저장소의 enrich_kakao.py 도 홈페이지 수집에 같은 경로를 이미 쓰고 있다)

  그래서 조심해서 돈다
    · 기본 초당 1.5건. 사람이 브라우징하는 속도를 크게 넘지 않는다.
    · 연속 실패가 쌓이면 스스로 멈춘다(차단 징후로 본다).
    · 한 건 끝날 때마다 파일에 쓴다. 중간에 끊겨도 --resume 으로 이어서 한다.

입력 : CSV (biz_no, place_url)
출력 : CSV (biz_no, operating_hours, homepage, note)  — 한 줄씩 append

사용:
  python scripts/enrich_kakao_place.py 입력.csv 출력.csv [건수] [--resume] [--rps=1.5]
"""
import csv
import io
import os
import re
import sys
import time

import httpx

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
API = "https://place-api.map.kakao.com/places/panel3/"

DAYS = "월화수목금토일"


def headers(pid):
    return {
        "User-Agent": UA,
        "Accept": "application/json",
        "Origin": "https://place.map.kakao.com",
        "Referer": f"https://place.map.kakao.com/{pid}",
        "pf": "web",
    }


def place_id(url):
    m = re.search(r"/(\d+)(?:[?#].*)?$", url or "")
    return m.group(1) if m else ""


def norm_time(span):
    """'10:00 ~ 07:30' -> '10:00~19:30'

    카카오는 오후 시간을 12시간제로 흘려보내는 경우가 있다. 끝시각이 시작보다
    이르고 12시 이전이면 오후로 본다. 치료기관이 자정을 넘겨 운영하는 경우는
    사실상 없으므로 이 보정은 안전하다.
    """
    m = re.match(r"\s*(\d{1,2}):(\d{2})\s*~\s*(\d{1,2}):(\d{2})\s*$", span or "")
    if not m:
        return (span or "").strip()
    sh, sm, eh, em = (int(x) for x in m.groups())
    if (eh * 60 + em) < (sh * 60 + sm) and eh < 12:
        eh += 12
    return f"{sh:02d}:{sm:02d}~{eh:02d}:{em:02d}"


def parse_hours(open_hours):
    """주간 운영시간을 '월~금 10:00~19:30, 토 09:30~18:30' 형태로 압축한다."""
    if not isinstance(open_hours, dict):
        return ""
    periods = ((open_hours.get("week_from_today") or {}).get("week_periods") or [])
    seq = []          # [(요일, 시간문자열)]
    for p in periods:
        for d in (p.get("days") or []):
            desc = d.get("day_of_the_week_desc") or ""
            day = desc[0] if desc and desc[0] in DAYS else ""
            if not day:
                continue
            on = d.get("on_days") or {}
            off = d.get("off_days") or {}
            if on.get("start_end_time_desc"):
                seq.append((day, norm_time(on["start_end_time_desc"])))
            elif off:
                seq.append((day, "휴무"))
    if not seq:
        return ""

    # 요일 순서대로 정렬하고 같은 값이 이어지면 묶는다
    order = {c: i for i, c in enumerate(DAYS)}
    seen = {}
    for day, val in seq:
        seen.setdefault(day, val)
    items = sorted(seen.items(), key=lambda kv: order[kv[0]])

    out, i = [], 0
    while i < len(items):
        j = i
        while (j + 1 < len(items)
               and items[j + 1][1] == items[i][1]
               and order[items[j + 1][0]] == order[items[j][0]] + 1):
            j += 1
        label = items[i][0] if i == j else f"{items[i][0]}~{items[j][0]}"
        out.append(f"{label} {items[i][1]}")
        i = j + 1
    return ", ".join(out)


def pick_homepage(summary):
    for u in (summary.get("homepages") or []):
        if isinstance(u, dict):
            u = u.get("url") or u.get("homepage") or ""
        if isinstance(u, str) and u.startswith("http") and "kakao" not in u:
            return u
    return ""


def main():
    src, dst = sys.argv[1], sys.argv[2]
    args = sys.argv[3:]
    limit = next((int(a) for a in args if a.isdigit()), 10 ** 9)
    resume = "--resume" in args
    rps = next((float(a.split("=", 1)[1]) for a in args if a.startswith("--rps=")), 1.5)
    delay = 1.0 / max(rps, 0.1)

    done = set()
    if resume and os.path.exists(dst):
        done = {r["biz_no"] for r in csv.DictReader(io.open(dst, encoding="utf-8-sig"))}
        print(f"이어서 진행 — 이미 처리 {len(done)}건", flush=True)

    rows = [r for r in csv.DictReader(io.open(src, encoding="utf-8-sig"))
            if r["biz_no"] not in done][:limit]
    print(f"대상 {len(rows)}곳  ({rps}건/초, 예상 {len(rows)*delay/60:.0f}분)", flush=True)

    new_file = not (resume and os.path.exists(dst))
    fp = io.open(dst, "w" if new_file else "a", encoding="utf-8-sig", newline="")
    w = csv.DictWriter(fp, fieldnames=["biz_no", "operating_hours", "homepage", "note"])
    if new_file:
        w.writeheader()
        fp.flush()

    client = httpx.Client(timeout=20, follow_redirects=True)
    n_hours = n_home = n_empty = 0
    consecutive_fail = 0

    for i, r in enumerate(rows, 1):
        pid = place_id(r.get("place_url", ""))
        if not pid:
            continue

        hours = home = ""
        note = ""
        try:
            resp = client.get(API + pid, headers=headers(pid))
            if resp.status_code in (403, 429):
                consecutive_fail += 1
                note = f"HTTP{resp.status_code}"
            elif resp.status_code != 200:
                note = f"HTTP{resp.status_code}"
                consecutive_fail = 0
            else:
                d = resp.json()
                hours = parse_hours(d.get("open_hours"))
                home = pick_homepage(d.get("summary") or {})
                consecutive_fail = 0
                if not hours:
                    note = "시간정보없음"
        except Exception as e:
            consecutive_fail += 1
            note = type(e).__name__

        if hours:
            n_hours += 1
        if home:
            n_home += 1
        if not hours and not home:
            n_empty += 1

        w.writerow({"biz_no": r["biz_no"], "operating_hours": hours,
                    "homepage": home, "note": note})
        fp.flush()          # 끊겨도 여기까지는 남는다

        # 차단 징후: 연속 실패가 쌓이면 더 두드리지 않고 멈춘다
        if consecutive_fail >= 8:
            print(f"\n!! 연속 실패 {consecutive_fail}건 — 차단으로 보고 중단합니다.", flush=True)
            print(f"   나중에 --resume 으로 이어서 하세요.", flush=True)
            break

        if i % 50 == 0:
            print(f"  {i}/{len(rows)}  운영시간 {n_hours} · 홈페이지 {n_home} · 빈값 {n_empty}",
                  flush=True)
        time.sleep(delay)

    fp.close()
    print(f"\n=== 결과 ===")
    print(f"  처리 {i if rows else 0}곳")
    print(f"  운영시간 {n_hours}건 · 홈페이지 {n_home}건 · 둘 다 없음 {n_empty}건")
    print(f"  파일: {dst}")


if __name__ == "__main__":
    main()
