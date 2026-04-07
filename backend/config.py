from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: str
    REDIS_URL: str
    API_SECRET: str
    ENCRYPTION_KEY: str
    COLLECTOR_INTERVAL: int = 60

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
