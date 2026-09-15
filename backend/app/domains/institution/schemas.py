from pydantic import BaseModel, Field


class InstitutionCard(BaseModel):
    """둘러보기 리스트 · 추천 결과 · 상세 상단이 공유하는 카드 (mv_institution_card 1행)"""
    biz_no: str
    name: str
    sido: str | None
    sigungu: str | None
    tel: str | None = None          # 카드에서 바로 전화를 걸 수 있어야 한다
    area_codes: list[str] = []
    area_names: list[str] = []
    price_min: int | None
    price_max: int | None
    price_year: int | None
    visit_available: bool
    link_url: str | None
    has_own_site: bool

    @property
    def price_label(self) -> str | None:
        if self.price_min is None:
            return None
        def man(v: int) -> str:                      # 53000 → '5.3', 70000 → '7'
            return f"{v / 10000:.1f}".rstrip("0").rstrip(".")
        lo, hi = man(self.price_min), man(self.price_max)
        return f"회기당 {lo}만원" if lo == hi else f"회기당 {lo}~{hi}만원"


class PriceRow(BaseModel):
    area_code: str
    area_name: str
    delivery_mode: str
    price_krw: int
    price_year: int
    disclosed_at: str | None


class InstitutionDetail(InstitutionCard):
    address: str | None
    lat: float | None
    lon: float | None
    operating_hours: str | None      # 카카오에서 확보한 곳만 (약 3분의 1) → 없으면 행 숨김
    prices: list[PriceRow]
    price_note: str                  # "2026년 공시 기준 · 변동될 수 있어요"


class InstitutionPage(BaseModel):
    total: int
    items: list[InstitutionCard]
    page: int = Field(ge=1)
    size: int
