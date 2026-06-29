from abc import ABC, abstractmethod
from collections import defaultdict

from backend.app.intelligence.models import (
    FusedMoment,
    MomentCandidate,
    SignalBatch,
    SignalContribution,
)
from backend.app.intelligence.profiles import RankingProfile


class FusionStrategy(ABC):
    @abstractmethod
    def fuse(
        self,
        candidates: tuple[MomentCandidate, ...],
        batches: tuple[SignalBatch, ...],
        profile: RankingProfile,
    ) -> tuple[FusedMoment, ...]:
        """Fuse normalized signals according to a ranking profile."""


class DeterministicWeightedFusion(FusionStrategy):
    def fuse(
        self,
        candidates: tuple[MomentCandidate, ...],
        batches: tuple[SignalBatch, ...],
        profile: RankingProfile,
    ) -> tuple[FusedMoment, ...]:
        signals_by_candidate = defaultdict(list)
        for batch in batches:
            for signal in batch.signals:
                signals_by_candidate[signal.candidate_id].append(signal)

        fused = []
        for candidate in candidates:
            contributions = []
            weighted_score_sum = 0.0
            confidence_weight_sum = 0.0
            profile_weight_sum = 0.0

            for signal in signals_by_candidate[candidate.candidate_id]:
                weight = profile.weights.get(signal.signal_name, 0.0)
                if weight <= 0:
                    continue
                weighted_value = signal.score * signal.confidence * weight
                contributions.append(
                    SignalContribution(
                        analyzer_id=signal.analyzer_id,
                        signal_name=signal.signal_name,
                        raw_score=signal.score,
                        confidence=signal.confidence,
                        weight=weight,
                        weighted_value=weighted_value,
                    )
                )
                weighted_score_sum += weighted_value
                confidence_weight_sum += signal.confidence * weight
                profile_weight_sum += weight

            score = (
                weighted_score_sum / confidence_weight_sum
                if confidence_weight_sum > 0
                else 0.0
            )
            confidence = (
                confidence_weight_sum / profile_weight_sum
                if profile_weight_sum > 0
                else 0.0
            )
            if score < profile.thresholds.minimum_score:
                continue
            if confidence < profile.thresholds.minimum_confidence:
                continue

            fused.append(
                FusedMoment(
                    candidate=candidate,
                    score=score,
                    confidence=confidence,
                    contributions=tuple(
                        sorted(
                            contributions,
                            key=lambda item: (-item.weighted_value, item.signal_name),
                        )
                    ),
                )
            )

        fused.sort(
            key=lambda item: (
                -item.score,
                -item.confidence,
                item.candidate.start_seconds,
                item.candidate.candidate_id,
            )
        )
        return tuple(fused)
