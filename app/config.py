import os
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")
    
    APP_NAME: str = "FCC Link"
    PORTAL_DOMAIN: str = "link.gajc.site"
    MANAGED_DOMAINS: str = "fcc.li,amp.ad,link.gajc.site"
    DEFAULT_SUPERADMIN: str = "freecommunitychurchsingapore@gmail.com"
    DATABASE_URL: str = "sqlite+aiosqlite:///./data/app.db"
    SECRET_KEY: str = os.getenv("SECRET_KEY", "fcc-link-session-secret-key-2026-very-secure")
    
    # Google OAuth
    GOOGLE_CLIENT_ID: str = os.getenv("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET: str = os.getenv("GOOGLE_CLIENT_SECRET", "")
    GOOGLE_REDIRECT_URI: str = os.getenv("GOOGLE_REDIRECT_URI", "https://link.gajc.site/auth/google/callback")
    
    # Dev bypass allows testing role management and link CRUD without Google Cloud setup
    DEV_AUTH_BYPASS: bool = os.getenv("DEV_AUTH_BYPASS", "true").lower() in ("true", "1", "yes")

    @property
    def domain_list(self) -> List[str]:
        return [d.strip() for d in self.MANAGED_DOMAINS.split(",") if d.strip()]

settings = Settings()
