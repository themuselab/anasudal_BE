import asyncpg

from app.core.config import get_settings
from app.core.gemini import gemini
from app.domains.knowledge import repository as repo
from app.domains.knowledge.schemas import Evidence


def to_evidence(r: asyncpg.Record) -> Evidence:
    sim = float(r["similarity"])
    return Evidence(
        chunk_id=r["chunk_id"], chunk_type=r["chunk_type"], content=r["content"],
        publisher=r["publisher"], source_title=r["source_title"],
        source_year=r["source_year"], source_url=r["source_url"],
        domain=(r["domain"] if "domain" in r.keys() else None),
        similarity=round(sim, 4), match_percent=int(round(sim * 100)),
    )


async def retrieve(conn, query: str, *, age_months: int | None, top_k: int | None = None) -> list[Evidence]:
    k = top_k or get_settings().top_k
    qvec = await gemini().embed(query, task="RETRIEVAL_QUERY")
    rows = await repo.vector_search(conn, qvec, age_months=age_months, top_k=k)
    return [to_evidence(r) for r in rows]
