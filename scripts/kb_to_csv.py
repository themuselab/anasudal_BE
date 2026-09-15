# -*- coding: utf-8 -*-
"""kb_chunks.jsonl + kb_vectors.jsonl -> data/kb_chunks.csv  (psql \\copy 용)
source 문자열을 kb_source.source_id(1~5)로 매핑하고, 벡터는 pgvector 텍스트 '[..]'로 직렬화한다.
"""
import json, io, os, csv

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
D = lambda *p: os.path.join(BASE, *p)


def source_id(src: str) -> int:
    if "K-DST" in src:
        return 1
    if "새싹과단비" in src:
        return 2
    if "국가건강정보포털" in src:
        return 3
    if "전자바우처" in src:
        return 4
    if "별표 5" in src:
        return 6
    if "아이사랑" in src:
        return 7
    if "정밀검사비" in src:
        return 8
    return 5


vec = {}
for l in io.open(D("data", "kb", "kb_vectors.jsonl"), encoding="utf-8"):
    r = json.loads(l)
    vec[r["id"]] = r["v"]

n = miss = 0
with io.open(D("data", "kb_chunks.csv"), "w", encoding="utf-8", newline="") as fp:
    w = csv.writer(fp)
    w.writerow(["chunk_id", "source_id", "chunk_type", "content",
                "age_lo", "age_hi", "domain", "meta", "embedding"])
    for l in io.open(D("data", "kb", "kb_chunks.jsonl"), encoding="utf-8"):
        c = json.loads(l)
        m = c.get("meta") or {}
        v = vec.get(c["id"])
        if v is None:
            miss += 1
        w.writerow([
            c["id"], source_id(c["source"]), c["type"], c["text"],
            m.get("age_lo", ""), m.get("age_hi", ""), m.get("domain", ""),
            json.dumps(m, ensure_ascii=False),
            "[" + ",".join("%.6f" % x for x in v) + "]" if v else "",
        ])
        n += 1
print("kb_chunks.csv: %d행 (임베딩 누락 %d)" % (n, miss))
