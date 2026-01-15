from dataclasses import dataclass
from functools import lru_cache
import os


@dataclass(frozen=True)
class Settings:
    openai_api_key: str
    wc_api_url: str
    wc_consumer_key: str
    wc_consumer_secret: str
    wc_brand_attribute_slug: str
    allowed_origins: list[str]
    coupon_min_discount: int
    coupon_max_discount: int
    coupon_default_duration_minutes: int
    redis_url: str
    # Session settings
    session_timeout_minutes: int
    conversation_memory_turns: int
    # Catalog settings
    catalog_refresh_minutes: int


@lru_cache
def get_settings() -> Settings:
    return Settings(
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        wc_api_url=os.getenv("WC_API_URL", ""),
        wc_consumer_key=os.getenv("WC_CONSUMER_KEY", ""),
        wc_consumer_secret=os.getenv("WC_CONSUMER_SECRET", ""),
        wc_brand_attribute_slug=os.getenv("WC_BRAND_ATTRIBUTE_SLUG", "pa_brand"),
        allowed_origins=[
            origin.strip()
            for origin in os.getenv("ALLOWED_ORIGINS", "").split(",")
            if origin.strip()
        ],
        coupon_min_discount=int(os.getenv("COUPON_MIN_DISCOUNT", "3")),
        coupon_max_discount=int(os.getenv("COUPON_MAX_DISCOUNT", "5")),
        coupon_default_duration_minutes=int(
            os.getenv("COUPON_DEFAULT_DURATION_MINUTES", "1440")  # 24 hours (expires end of tomorrow)
        ),
        redis_url=os.getenv("REDIS_URL", "redis://localhost:6379/0"),  # Default to local Redis for development
        # Session: 2 hours for shopping behavior
        session_timeout_minutes=int(os.getenv("SESSION_TIMEOUT_MINUTES", "120")),
        # Conversation: remember last 15 turns for better context
        conversation_memory_turns=int(os.getenv("CONVERSATION_MEMORY_TURNS", "15")),
        # Catalog: refresh every 10 minutes
        catalog_refresh_minutes=int(os.getenv("CATALOG_REFRESH_MINUTES", "10")),
    )


