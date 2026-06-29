from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping


@dataclass(frozen=True, slots=True)
class RankingThresholds:
    minimum_score: float = 0.0
    minimum_confidence: float = 0.0

    def __post_init__(self) -> None:
        if not 0 <= self.minimum_score <= 1:
            raise ValueError("minimum_score must be between 0 and 1")
        if not 0 <= self.minimum_confidence <= 1:
            raise ValueError("minimum_confidence must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class RankingProfile:
    profile_id: str
    weights: Mapping[str, float]
    thresholds: RankingThresholds

    def __post_init__(self) -> None:
        if not self.profile_id.strip():
            raise ValueError("profile_id cannot be empty")
        if any(weight < 0 for weight in self.weights.values()):
            raise ValueError("profile weights cannot be negative")
        object.__setattr__(self, "weights", MappingProxyType(dict(self.weights)))


class ProfileRegistry:
    def __init__(self, profiles: tuple[RankingProfile, ...] = ()) -> None:
        self._profiles: dict[str, RankingProfile] = {}
        for profile in profiles:
            self.register(profile)

    def register(self, profile: RankingProfile) -> None:
        if profile.profile_id in self._profiles:
            raise ValueError(f"ranking profile already registered: {profile.profile_id}")
        self._profiles[profile.profile_id] = profile

    def get(self, profile_id: str) -> RankingProfile:
        try:
            return self._profiles[profile_id]
        except KeyError as error:
            raise KeyError(f"unknown ranking profile: {profile_id}") from error


def default_ranking_profile() -> RankingProfile:
    return RankingProfile(
        profile_id="default",
        weights={
            "scene.duration": 0.35,
            "scene.position": 0.15,
            "transcript.word_density": 0.30,
            "transcript.coverage": 0.20,
        },
        thresholds=RankingThresholds(),
    )
