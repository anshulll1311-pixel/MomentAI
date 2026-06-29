from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict


class ExportPresetName(StrEnum):
    STANDARD = "standard"
    PREVIEW = "preview"
    HIGH_QUALITY = "high_quality"
    YOUTUBE_SHORTS = "youtube_shorts"
    TIKTOK = "tiktok"


@dataclass(frozen=True, slots=True)
class ExportPreset:
    name: ExportPresetName
    video_codec: str
    audio_codec: str
    encoder_preset: str
    crf: int
    audio_bitrate: str
    width: int | None = None
    height: int | None = None
    fit_mode: str = "source"
    fps: int | None = None


EXPORT_PRESETS: Mapping[ExportPresetName, ExportPreset] = MappingProxyType(
    {
        ExportPresetName.STANDARD: ExportPreset(
            name=ExportPresetName.STANDARD,
            video_codec="libx264",
            audio_codec="aac",
            encoder_preset="medium",
            crf=23,
            audio_bitrate="128k",
        ),
        ExportPresetName.PREVIEW: ExportPreset(
            name=ExportPresetName.PREVIEW,
            video_codec="libx264",
            audio_codec="aac",
            encoder_preset="veryfast",
            crf=30,
            audio_bitrate="96k",
            width=854,
            height=480,
            fit_mode="contain",
        ),
        ExportPresetName.HIGH_QUALITY: ExportPreset(
            name=ExportPresetName.HIGH_QUALITY,
            video_codec="libx264",
            audio_codec="aac",
            encoder_preset="slow",
            crf=18,
            audio_bitrate="192k",
        ),
        ExportPresetName.YOUTUBE_SHORTS: ExportPreset(
            name=ExportPresetName.YOUTUBE_SHORTS,
            video_codec="libx264",
            audio_codec="aac",
            encoder_preset="medium",
            crf=20,
            audio_bitrate="192k",
            width=1080,
            height=1920,
            fit_mode="pad",
            fps=30,
        ),
        ExportPresetName.TIKTOK: ExportPreset(
            name=ExportPresetName.TIKTOK,
            video_codec="libx264",
            audio_codec="aac",
            encoder_preset="medium",
            crf=21,
            audio_bitrate="128k",
            width=1080,
            height=1920,
            fit_mode="pad",
            fps=30,
        ),
    }
)


@dataclass(frozen=True, slots=True)
class ExportOptions:
    profile_id: str = "default"
    preset: ExportPresetName = ExportPresetName.STANDARD
    top_k: int = 5
    selected_ranks: tuple[int, ...] = ()
    padding_before_seconds: float = 0.0
    padding_after_seconds: float = 0.0

    def __post_init__(self) -> None:
        if not self.profile_id.strip():
            raise ValueError("profile_id cannot be empty")
        if not 1 <= self.top_k <= 20:
            raise ValueError("top_k must be between 1 and 20")
        if any(rank <= 0 for rank in self.selected_ranks):
            raise ValueError("selected ranks must be positive")
        if len(set(self.selected_ranks)) != len(self.selected_ranks):
            raise ValueError("selected ranks cannot contain duplicates")
        if not 0 <= self.padding_before_seconds <= 30:
            raise ValueError("padding_before_seconds must be between 0 and 30")
        if not 0 <= self.padding_after_seconds <= 30:
            raise ValueError("padding_after_seconds must be between 0 and 30")


@dataclass(frozen=True, slots=True)
class ContributionSnapshot:
    analyzer_id: str
    signal_name: str
    raw_score: float
    confidence: float
    weight: float
    weighted_value: float


@dataclass(frozen=True, slots=True)
class InsightSnapshot:
    insight_type: str
    summary: str
    evidence: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence", MappingProxyType(dict(self.evidence)))


@dataclass(frozen=True, slots=True)
class ClipSpec:
    clip_id: str
    candidate_id: str
    rank: int
    start_seconds: float
    end_seconds: float
    scene_ids: tuple[int, ...]
    score: float
    confidence: float
    contributions: tuple[ContributionSnapshot, ...]
    insights: tuple[InsightSnapshot, ...]

    @property
    def duration_seconds(self) -> float:
        return self.end_seconds - self.start_seconds


@dataclass(frozen=True, slots=True)
class ClipMediaMetadata:
    duration_seconds: float
    width: int
    height: int
    video_codec: str
    audio_codec: str | None
    size_bytes: int


@dataclass(frozen=True, slots=True)
class ClipArtifact:
    spec: ClipSpec
    path: Path
    metadata: ClipMediaMetadata
    sha256: str


class ManifestContribution(BaseModel):
    model_config = ConfigDict(frozen=True)

    analyzer_id: str
    signal_name: str
    raw_score: float
    confidence: float
    weight: float
    weighted_value: float


class ManifestInsight(BaseModel):
    model_config = ConfigDict(frozen=True)

    insight_type: str
    summary: str
    evidence: dict[str, Any]


class ManifestVideo(BaseModel):
    model_config = ConfigDict(frozen=True)

    duration_seconds: float
    width: int
    height: int
    fps: float
    video_codec: str
    audio_codec: str | None
    bitrate: int
    rotation: int | None
    file_size_bytes: int


class ManifestClip(BaseModel):
    model_config = ConfigDict(frozen=True)

    clip_id: str
    candidate_id: str
    rank: int
    start_seconds: float
    end_seconds: float
    duration_seconds: float
    scene_ids: list[int]
    score: float
    confidence: float
    contributions: list[ManifestContribution]
    insights: list[ManifestInsight]
    filename: str
    size_bytes: int
    sha256: str
    width: int
    height: int
    video_codec: str
    audio_codec: str | None


class ManifestDiagnostic(BaseModel):
    model_config = ConfigDict(frozen=True)

    stage: str
    status: str
    message: str


class ManifestExportOptions(BaseModel):
    model_config = ConfigDict(frozen=True)

    top_k: int
    selected_ranks: list[int]
    padding_before_seconds: float
    padding_after_seconds: float


class ExportManifest(BaseModel):
    model_config = ConfigDict(frozen=True)

    manifest_version: str
    momentai_version: str
    pipeline_version: str
    mie_version: str
    export_id: str
    created_at: datetime
    source_filename: str
    source_fingerprint: str
    profile: str
    preset: ExportPresetName
    options: ManifestExportOptions
    video: ManifestVideo
    diagnostics: list[ManifestDiagnostic]
    clips: list[ManifestClip]
    transforms: list[str]


@dataclass(frozen=True, slots=True)
class ExportResult:
    export_id: str
    profile_id: str
    preset: ExportPresetName
    artifacts: tuple[ClipArtifact, ...]
    manifest: ExportManifest
    manifest_path: Path
    package_path: Path
    package_sha256: str
