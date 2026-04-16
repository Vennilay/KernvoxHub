from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: str
    REDIS_URL: str
    REDIS_PASSWORD: str = ""
    API_SECRET: str
    API_TOKEN: str = ""
    ENCRYPTION_KEY: str
    INTERNAL_API_KEY: str = ""
    CORS_ORIGINS: str = "http://localhost,http://127.0.0.1,http://localhost:3000,http://127.0.0.1:3000"
    COLLECTOR_INTERVAL: int = 60

    @property
    def cors_origins_list(self) -> List[str]:
        origins = [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]
        return origins if origins != ["*"] else ["*"]

    @property
    def cors_allow_credentials(self) -> bool:
        return self.cors_origins_list != ["*"]

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
