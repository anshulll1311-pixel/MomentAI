from backend.app.intelligence.analyzers.base import SignalAnalyzer


class AnalyzerConfigurationError(ValueError):
    """Raised when analyzer registration or dependencies are invalid."""


class AnalyzerRegistry:
    def __init__(self, analyzers: tuple[SignalAnalyzer, ...] = ()) -> None:
        self._analyzers: dict[str, SignalAnalyzer] = {}
        for analyzer in analyzers:
            self.register(analyzer)

    def register(self, analyzer: SignalAnalyzer) -> None:
        analyzer_id = analyzer.metadata.analyzer_id
        if analyzer_id in self._analyzers:
            raise AnalyzerConfigurationError(f"analyzer already registered: {analyzer_id}")
        self._analyzers[analyzer_id] = analyzer

    def get(self, analyzer_id: str) -> SignalAnalyzer:
        try:
            return self._analyzers[analyzer_id]
        except KeyError as error:
            raise AnalyzerConfigurationError(f"unknown analyzer: {analyzer_id}") from error

    def execution_layers(self) -> tuple[tuple[SignalAnalyzer, ...], ...]:
        for analyzer in self._analyzers.values():
            missing = set(analyzer.metadata.dependencies) - self._analyzers.keys()
            if missing:
                missing_list = ", ".join(sorted(missing))
                raise AnalyzerConfigurationError(
                    f"analyzer {analyzer.metadata.analyzer_id} has missing dependencies: {missing_list}"
                )

        unresolved = set(self._analyzers)
        resolved: set[str] = set()
        layers: list[tuple[SignalAnalyzer, ...]] = []

        while unresolved:
            ready = [
                self._analyzers[analyzer_id]
                for analyzer_id in unresolved
                if set(self._analyzers[analyzer_id].metadata.dependencies) <= resolved
            ]
            if not ready:
                cycle = ", ".join(sorted(unresolved))
                raise AnalyzerConfigurationError(f"cyclic analyzer dependencies: {cycle}")

            ready.sort(key=lambda item: (item.metadata.priority, item.metadata.analyzer_id))
            layers.append(tuple(ready))
            ready_ids = {item.metadata.analyzer_id for item in ready}
            unresolved -= ready_ids
            resolved |= ready_ids

        return tuple(layers)
