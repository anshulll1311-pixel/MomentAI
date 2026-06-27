from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """Environment-backed application settings."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        env_prefix="MOMENTAI_",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "MomentAI API"
    environment: str = "development"
    api_prefix: str = "/api/v1"
    cors_origins: str = "http://localhost:3000"
    log_level: str = "INFO"
    max_upload_size_mb: int = Field(default=500, gt=0)
    upload_dir: Path = Path("uploads")
    thumbnail_dir: Path = Path("thumbnails")
    ffprobe_binary: str = "ffprobe"
    ffprobe_timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    ffmpeg_binary: str = "ffmpeg"
    ffmpeg_timeout_seconds: float = Field(default=30.0, gt=0, le=300)

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024

    @property
    def runtime_directories(self) -> tuple[Path, ...]:
        return (
            self.upload_dir,
            self.thumbnail_dir,
            PROJECT_ROOT / "clips",
            PROJECT_ROOT / "frames",
            PROJECT_ROOT / "temp",
        )

    def model_post_init(self, __context: object) -> None:
        if not self.upload_dir.is_absolute():
            self.upload_dir = PROJECT_ROOT / self.upload_dir
        if not self.thumbnail_dir.is_absolute():
            self.thumbnail_dir = PROJECT_ROOT / self.thumbnail_dir


@lru_cache
def get_settings() -> Settings:
    return Settings()
