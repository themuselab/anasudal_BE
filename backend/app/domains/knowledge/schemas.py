from pydantic import BaseModel


class Evidence(BaseModel):
    """근거 자료 카드 (mv_kb_evidence + 유사도)"""
    chunk_id: str
    chunk_type: str
    content: str
    publisher: str
    source_title: str
    source_year: int | None
    source_url: str | None
    similarity: float
    match_percent: int          # 화면 표기 "82% 일치"


class SearchRequest(BaseModel):
    query: str
    age_months: int | None = None
    top_k: int | None = None


class SearchResponse(BaseModel):
    items: list[Evidence]
    age_filter_applied: bool
