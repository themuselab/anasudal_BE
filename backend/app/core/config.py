from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str
    gemini_api_key: str = ""
    gemini_embed_model: str = "models/gemini-embedding-2"
    gemini_gen_model: str = "models/gemini-3.6-flash"
    gemini_thinking_level: str = "low"   # 측정: low → 첫 글자 1.4s/전체 3.1s (기본 7.5s/8.9s). 근거 요약엔 충분
    embed_dim: int = 768
    top_k: int = 3                      # 측정: k=3에서 적중 96% / 정밀 80%
    session_ttl_hours: int = 24
    cors_origins: str = "http://localhost:3000"

    # Redis (없으면 캐시·제한 비활성)
    redis_url: str | None = None
    cache_ttl_read: int = 600             # 지역·기관 조회 캐시 (초)
    cache_ttl_embed: int = 7 * 24 * 3600  # 질문 임베딩 캐시
    ask_rate_limit_per_hour: int = 60     # IP당 /chat/ask 상한 (로그인 없음 → Gemini 남용 방지; 심사장 공용 IP 감안)
    prompt_count: int = 3                 # 첫 화면 칩 개수

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
