# -*- coding: utf-8 -*-
"""SSIS(사회서비스 전자바우처 제공기관) 원본에서 아직 DB 에 안 들어간 칸을 채운다.

병합 당시 signguName 이 "경기도 포천시" 처럼 시·도를 앞에 달고 오는 걸 놓쳐서
시·군·구 대조가 거의 다 빗나갔다. 마지막 토큰만 쓰면 붙는다.

붙이는 기준
  이름(정규화) + 시·도 가 같을 것. 시·도까지 같은데 이름이 겹치는 기관은
  어느 쪽인지 알 수 없으므로 버린다.
이미 값이 있는 칸은 건드리지 않는다.

사용: DSN=... python scripts/apply_ssis_fill.py [--dry-run]
"""
import asyncio
import collections
import csv
import io
import os
import sys

import re

import asyncpg

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("KAKAO_KEY", "-")
from match_kakao_rescue import norm  # noqa: E402

SRC = "data/ssis_dev_rehab.csv"

# 형태만 본다. 시·도별 지역번호로 거르면 안 된다 — 부천은 032, 경산은 053,
# 계룡은 042 처럼 인접 권역 국번을 쓰는 시·군이 많다. 기존 파이프라인이 그
# 규칙으로 멀쩡한 번호를 버려서 전화 빈칸이 생겼다.
TEL_OK = re.compile(r"^(02|0[3-6][1-4]|050\d|070|080|1[3-9]\d\d)\d{6,9}$")


def valid_tel(t: str) -> bool:
    return bool(TEL_OK.match(re.sub(r"\D", "", t or "")))


def sigungu(s: str) -> str:
    return (s or "").strip().split()[-1] if (s or "").strip() else ""


async def main() -> None:
    dry = "--dry-run" in sys.argv
    dsn = os.environ.get("DSN") or sys.exit("DSN 환경변수가 필요합니다")

    rows = list(csv.DictReader(io.open(SRC, encoding="utf-8-sig")))
    # 한 기관이 서비스유형마다 한 줄씩 나온다 → 키별로 값이 있는 쪽을 남긴다
    merged: dict[tuple[str, str], dict] = {}
    for r in rows:
        k = (norm(r["providerName"]), r["sidoName"].strip())
        cur = merged.setdefault(k, {"email": "", "tel": "", "addr": "", "sigungu": sigungu(r["signguName"])})
        cur["email"] = cur["email"] or r["email"].strip()
        cur["tel"] = cur["tel"] or (r["telNumber"] or "").strip()
        addr = " ".join(x for x in ((r.get("loadAddress") or "").strip(),
                                    (r.get("loadAddressDetail") or "").strip()) if x)
        cur["addr"] = cur["addr"] or addr

    dup = {n for n, c in collections.Counter(n for n, _ in merged).items() if c > 1}

    conn = await asyncpg.connect(dsn)
    inst = await conn.fetch("""SELECT i.biz_no, i.name, i.address, i.tel, i.email, r.sido
        FROM institution i LEFT JOIN region r ON r.region_id = i.region_id""")

    plan = []
    ambiguous = 0
    for i in inst:
        n = norm(i["name"])
        if n in dup:
            ambiguous += 1
            continue
        r = merged.get((n, (i["sido"] or "").strip()))
        if not r:
            continue
        email = r["email"] if not i["email"] else None
        tel = r["tel"] if (not i["tel"] and valid_tel(r["tel"])) else None
        addr = r["addr"] if not i["address"] else None
        if email or tel or addr:
            plan.append((i["biz_no"], email, tel, addr))

    g = collections.Counter()
    for _, e, t, a in plan:
        g["email"] += bool(e); g["tel"] += bool(t); g["address"] += bool(a)
    print(f"이름이 한 시·도 안에서 유일한 건만 사용 (중복이라 건너뛴 기관 {ambiguous}곳)")
    print(f"채울 기관 {len(plan)}곳 -> 이메일 +{g['email']}, 전화 +{g['tel']}, 주소 +{g['address']}")
    if dry:
        await conn.close()
        return

    async with conn.transaction():
        for biz, email, tel, addr in plan:
            await conn.execute(
                """UPDATE institution SET
                     email      = COALESCE(NULLIF(email,''),   NULLIF($2,'')),
                     tel        = COALESCE(NULLIF(tel,''),     NULLIF($3,'')),
                     address    = COALESCE(NULLIF(address,''), NULLIF($4,'')),
                     updated_at = now()
                   WHERE biz_no = $1""",
                biz, email or "", (tel or "")[:20], addr or "")
    await conn.execute("SELECT refresh_all_mvs()")
    r = await conn.fetchrow("""SELECT count(email) e, count(tel) t, count(address) a, count(*) n
                               FROM institution""")
    print(f"반영 후 — 이메일 {r['e']} · 전화 {r['t']} · 주소 {r['a']} / {r['n']}")
    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
