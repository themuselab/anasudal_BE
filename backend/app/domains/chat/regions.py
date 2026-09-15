"""부모가 쓴 문장에서 지역을 알아낸다.

"분당 근처 언어치료 기관 추천해주세요" 처럼 지역이 이미 문장에 있는데도 화면이
시·도 → 시·군·구를 다시 고르게 하면, 방금 말한 걸 또 말하라는 뜻이 된다.

원칙은 하나다 — **확실할 때만 고른다.** "광주"는 광주광역시이기도 하고 경기도 광주시이기도
하다. 이런 건 넘겨서 화면이 묻게 둔다. 잘못 고르면 엉뚱한 동네 기관을 추천하게 되고,
부모는 그게 틀렸다는 걸 알아채기도 어렵다.
"""
from __future__ import annotations

import re
import time

import asyncpg

# 시·도 표기 흔들림 — 부모는 "경기", 데이터는 "경기도"
_SIDO_ALIAS = {
    "서울": "서울특별시", "부산": "부산광역시", "대구": "대구광역시", "인천": "인천광역시",
    "광주광역": "광주광역시", "대전": "대전광역시", "울산": "울산광역시", "세종": "세종특별자치시",
    "경기": "경기도", "강원": "강원특별자치도", "충북": "충청북도", "충남": "충청남도",
    "전북": "전북특별자치도", "전남": "전라남도", "경북": "경상북도", "경남": "경상남도",
    "제주": "제주특별자치도", "충청북": "충청북도", "충청남": "충청남도", "전라남": "전라남도",
    "경상북": "경상북도", "경상남": "경상남도",
}

# 시·도 이름과 겹치는 시·군·구 이름. "광주"는 광주광역시이기도 하고 경기도 광주시이기도 하고,
# "제주"는 제주도 전체이기도 하고 제주시이기도 하다. 시·도를 함께 적지 않았으면 고르지 않는다.
_SIDO_STEMS = {"서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종",
               "경기", "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주"}

# 부모가 실제로 쓰는 동네 이름 → 행정구역. 행정구역 표에 없어서 그냥 두면 매번 다시 묻게 된다.
# 두 시에 걸친 이름(광교·위례)은 넣지 않는다 — 어느 쪽인지 알 수 없다.
_AREA_ALIAS = {
    "분당": ("경기도", "성남시"), "판교": ("경기도", "성남시"),
    "일산": ("경기도", "고양시"), "동탄": ("경기도", "화성시"),
    "평촌": ("경기도", "안양시"), "산본": ("경기도", "군포시"),
    "송도": ("인천광역시", "연수구"), "청라": ("인천광역시", "서구"),
    "목동": ("서울특별시", "양천구"), "잠실": ("서울특별시", "송파구"),
    "여의도": ("서울특별시", "영등포구"), "상암": ("서울특별시", "마포구"),
}

_TTL = 600.0  # 지역 표는 거의 안 바뀐다. 10분이면 충분하다
_cache: tuple[float, list[dict]] | None = None


async def _regions(conn: asyncpg.Connection) -> list[dict]:
    global _cache
    now = time.monotonic()
    if _cache and now - _cache[0] < _TTL:
        return _cache[1]
    rows = await conn.fetch("SELECT region_id, sido, sigungu FROM region")
    data = [{"region_id": r["region_id"], "sido": r["sido"], "sigungu": r["sigungu"]} for r in rows]
    _cache = (now, data)
    return data


def _keys(sigungu: str) -> list[str]:
    """'성남시' → ['성남시', '성남'],  '고양시 덕양구' → ['고양시 덕양구', '덕양구', '덕양']"""
    out = [sigungu]
    last = sigungu.split()[-1]
    if last != sigungu:
        out.append(last)
    stem = re.sub(r"(특별자치시|광역시|시|군|구)$", "", last)
    if len(stem) >= 2:
        out.append(stem)
    return out


def _sido_in(message: str) -> str | None:
    """문장에 시·도가 적혀 있으면 정식 이름으로"""
    for alias, full in sorted(_SIDO_ALIAS.items(), key=lambda kv: -len(kv[0])):
        if alias in message:
            return full
    return None


async def find_region(conn: asyncpg.Connection, message: str) -> dict | None:
    """문장에서 시·군·구를 찾는다. 확실하지 않으면 None."""
    regions = await _regions(conn)
    sido = _sido_in(message)

    # 동네 이름이 먼저다 — "분당"은 행정구역 표에 없지만 성남시가 확실하다
    for alias, (a_sido, a_sigungu) in sorted(_AREA_ALIAS.items(), key=lambda kv: -len(kv[0])):
        if alias in message:
            hit = next((r for r in regions if r["sido"] == a_sido and r["sigungu"] == a_sigungu), None)
            if hit:
                return hit

    # 가장 긴 표기부터 본다 — "성남시 분당구"가 있으면 "성남"보다 그쪽이 맞다
    hits: list[tuple[int, dict]] = []
    for r in regions:
        for key in _keys(r["sigungu"]):
            if key in message:
                hits.append((len(key), r))
                break

    if not hits:
        return None

    best = max(h[0] for h in hits)
    picked = [r for n, r in hits if n == best]

    # "광주"·"제주" 처럼 시·도 이름과 글자가 겹치는 짧은 표기는 근거로 쓰지 않는다.
    # "제주도에서 찾고 있어요"는 제주시가 아니라 제주도 전체를 뜻하고, "광주"만으로는
    # 광주광역시인지 경기도 광주시인지 알 수 없다. "제주시"·"광주시"라고 적었으면
    # 더 긴 표기가 잡히므로 여기 걸리지 않는다.
    matched_key = next((k for r in picked for k in _keys(r["sigungu"]) if len(k) == best and k in message), "")
    if matched_key in _SIDO_STEMS:
        return None

    if sido:                                           # 시·도를 함께 적었으면 그 안에서만 고른다
        narrowed = [r for r in picked if r["sido"] == sido]
        if not narrowed:
            return None                                # "광주광역시 ..." 인데 후보가 경기도 광주시뿐
        picked = narrowed

    if len(picked) != 1:                               # 같은 이름이 여러 시·도에 — 화면이 묻게 둔다
        return None
    return picked[0]
