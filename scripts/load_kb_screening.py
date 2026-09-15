# -*- coding: utf-8 -*-
"""새로 만든 청크만 DB 에 반영한다 (전체 재적재 없이).

db/02_load.sql 은 psql \copy 로 전부를 다시 넣는다. 도커 없이, 그리고 이미
돌고 있는 서비스를 건드리지 않고 증분만 넣으려고 따로 둔다.

사용: DSN=... python scripts/load_kb_screening.py [--dry-run]
"""
import asyncio
import io
import json
import os
import sys

import asyncpg

# source 문자열 → (publisher, title, year, url, license)
SOURCES = {
    "보건복지부 건강검진 실시기준 [별표 5] 영유아건강검진 결과 판정기준": (
        "보건복지부", "건강검진 실시기준 [별표 5] 영유아건강검진 결과 판정기준", 2026,
        "https://www.law.go.kr/LSW//flDownload.do?flSeq=136957893",
        "저작권법 제7조 — 국가의 고시·공고는 보호 대상 아님"),
    "임신육아종합포털 아이사랑 (보건복지부·한국사회보장정보원)": (
        "보건복지부·한국사회보장정보원", "임신육아종합포털 아이사랑 — 조기지원", 2026,
        "https://www.childcare.go.kr/?menuno=661", "공공누리 (출처표시)"),
    "정부24·국민건강보험공단 영유아 발달 정밀검사비 지원": (
        "정부24·국민건강보험공단", "영유아 발달 정밀검사비 지원", 2026,
        "https://www.gov.kr/portal/service/serviceInfo/SD0000016095", "공공누리 (출처표시)"),
}


async def main() -> None:
    dry = "--dry-run" in sys.argv
    dsn = os.environ.get("DSN") or sys.exit("DSN 환경변수가 필요합니다")

    vec = {}
    for ln in io.open("data/kb/kb_vectors.jsonl", encoding="utf-8"):
        r = json.loads(ln)
        vec[r["id"]] = r["v"]
    new = [json.loads(ln) for ln in io.open("data/kb/kb_chunks.jsonl", encoding="utf-8")
           if json.loads(ln)["type"] == "screening"]
    missing = [c["id"] for c in new if c["id"] not in vec]
    if missing:
        sys.exit(f"임베딩이 없는 청크가 있습니다: {missing[:3]}")

    conn = await asyncpg.connect(dsn)
    before = await conn.fetchval("SELECT count(*) FROM kb_chunk")
    print(f"현재 청크 {before:,} · 넣을 청크 {len(new)}")
    if dry:
        for c in new[:3]:
            print(f"  {c['id']:<28} {c['text'][:56]}")
        await conn.close()
        return

    async with conn.transaction():
        sid = {}
        for key, (pub, title, year, url, lic) in SOURCES.items():
            sid[key] = await conn.fetchval(
                """INSERT INTO kb_source (publisher, title, year, url, license)
                   VALUES ($1,$2,$3,$4,$5)
                   ON CONFLICT (publisher, title) DO UPDATE SET url = EXCLUDED.url,
                       year = EXCLUDED.year, license = EXCLUDED.license
                   RETURNING source_id""", pub, title, year, url, lic)
        for c in new:
            m = c.get("meta") or {}
            await conn.execute(
                """INSERT INTO kb_chunk (chunk_id, source_id, chunk_type, content,
                                         age_lo, age_hi, domain, meta, embedding)
                   VALUES ($1,$2,$3,$4,NULL,NULL,NULL,$5::jsonb,$6::vector)
                   ON CONFLICT (chunk_id) DO UPDATE SET
                     source_id = EXCLUDED.source_id, content = EXCLUDED.content,
                     meta = EXCLUDED.meta, embedding = EXCLUDED.embedding""",
                c["id"], sid[c["source"]], c["type"], c["text"],
                json.dumps(m, ensure_ascii=False),
                "[" + ",".join("%.6f" % x for x in vec[c["id"]]) + "]")
    await conn.execute("REFRESH MATERIALIZED VIEW mv_kb_evidence")
    after = await conn.fetchval("SELECT count(*) FROM kb_chunk")
    emb = await conn.fetchval("SELECT count(*) FROM kb_chunk WHERE embedding IS NOT NULL")
    print(f"반영 후 청크 {after:,} (임베딩 {emb:,}) — 근거 뷰 갱신 완료")
    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
