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
    scene_threshold: float = Field(default=0.3, gt=0, lt=1)
    minimum_scene_duration_seconds: float = Field(default=0.5, gt=0)
    scene_detection_timeout_seconds: float = Field(default=120.0, gt=0, le=1800)
    transcript_temp_dir: Path = Path("temp/transcripts")
    whisper_model_dir: Path = Path("temp/whisper-models")
    whisper_model_size: str = "tiny.en"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"
    whisper_beam_size: int = Field(default=5, gt=0, le=20)
    audio_extraction_timeout_seconds: float = Field(default=60.0, gt=0, le=1800)
    transcription_timeout_seconds: float = Field(default=600.0, gt=0, le=7200)
    export_dir: Path = Path("clips/exports")
    export_temp_dir: Path = Path("temp/exports")
    export_ffmpeg_timeout_seconds: float = Field(default=300.0, gt=0, le=7200)
    export_ffprobe_timeout_seconds: float = Field(default=30.0, gt=0, le=300)

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
            self.transcript_temp_dir,
            self.whisper_model_dir,
            self.export_dir,
            self.export_temp_dir,
        )

    def model_post_init(self, __context: object) -> None:
        if not self.upload_dir.is_absolute():
            self.upload_dir = PROJECT_ROOT / self.upload_dir
        if not self.thumbnail_dir.is_absolute():
            self.thumbnail_dir = PROJECT_ROOT / self.thumbnail_dir
        if not self.transcript_temp_dir.is_absolute():
            self.transcript_temp_dir = PROJECT_ROOT / self.transcript_temp_dir
        if not self.whisper_model_dir.is_absolute():
            self.whisper_model_dir = PROJECT_ROOT / self.whisper_model_dir
        if not self.export_dir.is_absolute():
            self.export_dir = PROJECT_ROOT / self.export_dir
        if not self.export_temp_dir.is_absolute():
            self.export_temp_dir = PROJECT_ROOT / self.export_temp_dir


@lru_cache
def get_settings() -> Settings:
    return Settings()
