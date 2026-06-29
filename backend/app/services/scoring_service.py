"""Reusable scene scoring engine with abstract scorer and AI provider interfaces.

Architecture
────────────
BaseScorer (ABC)          Route depends only on this interface.
├── DeterministicScorer   Milestone 5 — deterministic placeholder scoring.
└── AIScorer              Pluggable AI scorer (ready for future milestones).
    └── BaseAIProvider     Abstract interface for LLM providers.
        ├── GeminiProvider   (future)
        ├── NemotronProvider (future)
        └── OpenAIProvider   (future)

Switching scorers or AI providers never requires route or schema changes.
"""

import logging
import math
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from backend.app.services.scene_service import Scene
from backend.app.services.transcript_service import TranscriptSegment

logger = logging.getLogger(__name__)


class ScoringError(RuntimeError):
    """Base error for scoring failures."""


# ── Dataclasses ──────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ScoredScene:
    """A single scene with its computed scores and optional AI metadata."""

    scene_id: int
    start_seconds: float
    end_seconds: float
    duration_seconds: float
    thumbnail_path: Path
    score: float
    duration_score: float
    position_score: float
    transcript_score: float
    reasoning: str | None = None
    confidence: float | None = None


@dataclass(frozen=True, slots=True)
class ScoringResult:
    """The full output of a scorer, sorted by score descending."""

    video_duration_seconds: float
    scene_count: int
    scenes: tuple[ScoredScene, ...]
    model_name: str | None = None

# ── Abstract Scorer Interface ────────────────────────────────────────────────


class BaseScorer(ABC):
    """Abstract interface for all scene scoring engines.

    Every scorer (deterministic or AI-powered) implements this contract
    so that consuming routes never depend on a concrete implementation.
    """

    @abstractmethod
    async def score(
        self,
        video_duration_seconds: float,
        scenes: tuple[Scene, ...],
        segments: tuple[TranscriptSegment, ...],
    ) -> ScoringResult:
        """Score every detected scene and return a ranked result.

        Args:
            video_duration_seconds: Total duration of the source video.
            scenes: Detected scene boundaries with thumbnails.
            segments: Transcript segments mapped to scene IDs (may be empty).

        Returns:
            ScoringResult with scenes sorted by score descending.
        """


# ── Abstract AI Provider Interface ──────────────────────────────────────────


class BaseAIProvider(ABC):
    """Abstract interface for LLM-based AI scoring providers.

    Each provider (Gemini, Nemotron, OpenAI, etc.) implements this
    interface so that AIScorer can switch models without route or
    schema changes.
    """

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Human-readable name of the AI model (e.g. 'gemini-2.5-flash')."""

    @abstractmethod
    async def analyze_scenes(
        self,
        video_duration_seconds: float,
        scenes: tuple[Scene, ...],
        segments: tuple[TranscriptSegment, ...],
    ) -> ScoringResult:
        """Analyze scenes using the AI model and return scored results.

        The provider is responsible for constructing the prompt, calling
        the LLM, parsing the response, and producing a ScoringResult.
        """

