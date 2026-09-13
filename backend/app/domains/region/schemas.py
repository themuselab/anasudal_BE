from pydantic import BaseModel


class Sido(BaseModel):
    sido: str
    institution_count: int


class Region(BaseModel):
    region_id: int
    sido: str
    sigungu: str
    institution_count: int
