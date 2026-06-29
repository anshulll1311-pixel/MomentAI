"""Replaceable artifact lifecycle boundary with a minimal local adapter."""

import asyncio
from abc import ABC, abstractmethod
from pathlib import Path

from backend.app.analysis.errors import ArtifactLifecycleError
from backend.app.analysis.models import ArtifactKind, ArtifactReference


class ArtifactManager(ABC):
    @abstractmethod
    def reference(self, kind: ArtifactKind, path: Path) -> ArtifactReference:
        """Create a stable reference without copying artifact bytes."""

    @abstractmethod
    def resolve(self, reference: ArtifactReference) -> Path:
        """Resolve a reference for a local consumer such as FFmpeg."""

    @abstractmethod
    async def delete(self, reference: ArtifactReference) -> None:
        """Retire one managed artifact if it still exists."""

    async def delete_many(self, references: tuple[ArtifactReference, ...]) -> None:
        await asyncio.gather(*(self.delete(reference) for reference in references))


class LocalArtifactManager(ArtifactManager):
    """Local-path adapter constrained to explicit runtime roots."""

    def __init__(self, managed_roots: tuple[Path, ...]) -> None:
        roots = tuple(root.resolve() for root in managed_roots)
        if not roots:
            raise ValueError("at least one managed artifact root is required")
        self._roots = roots

    def reference(self, kind: ArtifactKind, path: Path) -> ArtifactReference:
        resolved = path.resolve()
        self._assert_managed(resolved)
        return ArtifactReference(kind=kind, location=resolved.as_posix())

    def resolve(self, reference: ArtifactReference) -> Path:
        resolved = Path(reference.location).resolve()
        self._assert_managed(resolved)
        return resolved

    async def delete(self, reference: ArtifactReference) -> None:
        path = self.resolve(reference)
        try:
            await asyncio.to_thread(path.unlink, missing_ok=True)
        except OSError as error:
            raise ArtifactLifecycleError(
                f"Managed artifact could not be deleted: {path.name}."
            ) from error

    def _assert_managed(self, path: Path) -> None:
        if not any(path == root or path.is_relative_to(root) for root in self._roots):
            raise ArtifactLifecycleError("artifact path is outside configured runtime roots")

