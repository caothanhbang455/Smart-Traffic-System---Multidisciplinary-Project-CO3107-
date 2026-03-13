from functools import lru_cache
from pydantic import AnyHttpUrl, BaseSettings


class Settings(BaseSettings):
    app_name: str = "Smart Traffic System"
    backend_host: str = "0.0.0.0"
    backend_port: int = 8000
    public_backend_url: AnyHttpUrl | None = None
    frontend_origin: AnyHttpUrl | None = None
    database_url: str = "sqlite:///./traffic.db"
    websocket_interval_sec: int = 3
    ai_enabled: bool = True
    controllable_modes: list[str] = ["AUTO", "ADAPTIVE", "MANUAL"]

    class Config:
        env_file = ".env"


@lru_cache
def get_settings() -> Settings:
    return Settings()