import json
import unittest
from types import SimpleNamespace

from pydantic import SecretStr

from backend.app.semantic import (
    ProviderRegistry,
    SemanticResultStatus,
    create_semantic_intelligence_service,
)
from backend.app.semantic.models import ContentOrigin, SemanticMomentStatus
from backend.app.semantic.providers import GeminiProvider, GeminiProviderConfig
from tests.test_semantic_foundation import analysis_result


class MockGeminiModels:
    def __init__(self, response: object | Exception) -> None:
        self._response = response
        self.calls: list[dict[str, object]] = []

    async def generate_content(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


class MockGeminiClient:
    def __init__(self, models: MockGeminiModels) -> None:
        self.aio = SimpleNamespace(models=models)


def gemini_response(moment_payloads: list[dict[str, object]]) -> object:
    return SimpleNamespace(
        text=json.dumps({"moments": moment_payloads}),
        response_id="mock-gemini-response",
        usage_metadata=SimpleNamespace(
            prompt_token_count=240,
            candidates_token_count=160,
        ),
        candidates=(SimpleNamespace(finish_reason=SimpleNamespace(name="STOP")),),
    )


def valid_moment(candidate_id: str) -> dict[str, object]:
    return {
        "candidate_id": candidate_id,
        "title": f"Title for {candidate_id}",
        "description": f"Description for {candidate_id}",
        "hashtags": ["#MomentAI", "#Highlight"],
        "explanation": f"Deterministic evidence supports {candidate_id}.",
    }


def semantic_service(response: object | Exception) -> tuple[object, MockGeminiModels]:
    models = MockGeminiModels(response)
    provider = GeminiProvider(
        GeminiProviderConfig(
            api_key=SecretStr("mock-api-key"),
            model_id="mock-gemini-model",
        ),
        client=MockGeminiClient(models),
    )
    return (
        create_semantic_intelligence_service(ProviderRegistry((provider,))),
        models,
    )


class SemanticGenerationTests(unittest.IsolatedAsyncioTestCase):
    async def test_mock_gemini_generates_one_validated_batch_for_multiple_moments(
        self,
    ) -> None:
        service, models = semantic_service(
            gemini_response([valid_moment("scene-1"), valid_moment("scene-2")])
        )

        result = await service.enrich(await analysis_result())

        self.assertEqual(result.status, SemanticResultStatus.COMPLETE)
        self.assertEqual(result.batch_count, 1)
        self.assertEqual(len(models.calls), 1)
        self.assertEqual([moment.candidate_id for moment in result.moments], ["scene-1", "scene-2"])
        self.assertTrue(
            all(moment.status is SemanticMomentStatus.ENRICHED for moment in result.moments)
        )
        self.assertTrue(all(moment.category is None for moment in result.moments))
        self.assertTrue(all(moment.viral_potential is None for moment in result.moments))

        call = models.calls[0]
        self.assertIn("scene-1", call["contents"])
        self.assertIn("scene-2", call["contents"])
        schema = call["config"]["response_json_schema"]
        required = schema["properties"]["moments"]["items"]["required"]
        self.assertEqual(
            required,
            ["candidate_id", "title", "description", "hashtags", "explanation"],
        )

    async def test_invalid_provider_moment_uses_localized_deterministic_fallback(
        self,
    ) -> None:
        invalid = valid_moment("scene-2")
        invalid["description"] = ""
        service, _ = semantic_service(
            gemini_response([valid_moment("scene-1"), invalid])
        )

        result = await service.enrich(await analysis_result())

        self.assertEqual(result.status, SemanticResultStatus.PARTIAL)
        self.assertIs(result.moments[0].status, SemanticMomentStatus.ENRICHED)
        self.assertIs(result.moments[1].status, SemanticMomentStatus.DEGRADED)
        self.assertIs(
            result.moments[1].content_origin,
            ContentOrigin.DETERMINISTIC_FALLBACK,
        )
        self.assertTrue(
            any(
                diagnostic.stage == "validation"
                and diagnostic.candidate_id == "scene-2"
                for diagnostic in result.diagnostics
            )
        )

    async def test_provider_failure_falls_back_for_the_entire_batch(self) -> None:
        service, models = semantic_service(ConnectionError("mock provider unavailable"))

        result = await service.enrich(await analysis_result())

        self.assertEqual(len(models.calls), 1)
        self.assertEqual(result.status, SemanticResultStatus.DEGRADED)
        self.assertTrue(
            all(
                moment.content_origin is ContentOrigin.DETERMINISTIC_FALLBACK
                for moment in result.moments
            )
        )
        self.assertTrue(
            any(
                diagnostic.stage == "provider"
                and diagnostic.status == "degraded"
                for diagnostic in result.diagnostics
            )
        )


if __name__ == "__main__":
    unittest.main()
