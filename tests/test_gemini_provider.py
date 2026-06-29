import asyncio
import json
import sys
import unittest
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch

from pydantic import SecretStr

from backend.app.semantic.errors import ProviderTimeoutError
from backend.app.semantic.models import (
    GenerationParameters,
    ProviderBatchRequest,
    ProviderFinishReason,
    RenderedPrompt,
    SemanticBatch,
    SemanticMomentContext,
    ContextCompleteness,
)
from backend.app.semantic.providers import (
    GeminiProvider,
    GeminiProviderConfig,
    GeminiRetryPolicy,
    GeminiSafetySetting,
    ProviderRegistry,
)


class FakeModels:
    def __init__(self, response: object) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    async def generate_content(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        return self.response


class BlockingModels:
    async def generate_content(self, **kwargs: object) -> object:
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


class FakeClient:
    def __init__(self, models: object) -> None:
        self.aio = SimpleNamespace(models=models)


def provider_config(*, timeout_seconds: float = 5.0) -> GeminiProviderConfig:
    return GeminiProviderConfig(
        api_key=SecretStr("configuration-supplied-test-key"),
        model_id="gemini-test-model",
        model_version="test-version",
        timeout_seconds=timeout_seconds,
        retry_policy=GeminiRetryPolicy(attempts=4),
        safety_settings=(
            GeminiSafetySetting(
                category="HARM_CATEGORY_HATE_SPEECH",
                threshold="BLOCK_ONLY_HIGH",
            ),
        ),
    )


def batch_request() -> ProviderBatchRequest:
    moment = SemanticMomentContext(
        candidate_id="scene-1",
        rank=1,
        start_seconds=0.0,
        end_seconds=5.0,
        scene_ids=(1,),
        deterministic_score=0.8,
        deterministic_confidence=0.9,
        transcript_excerpt="A test transcript.",
        contributions=(),
        deterministic_insights=(),
        context_completeness=ContextCompleteness.FULL,
    )
    return ProviderBatchRequest(
        request_id="semantic-request-1",
        source_fingerprint="a" * 64,
        batch=SemanticBatch(
            batch_id="batch-1",
            moments=(moment,),
            estimated_input_tokens=100,
        ),
        prompt=RenderedPrompt(
            prompt_id="test-prompt",
            prompt_version="v1",
            schema_version="1.0.0",
            template_hash="template-hash",
            system_message="System instructions supplied by the prompt layer.",
            user_message="Rendered user content supplied by the prompt layer.",
            rendered_hash="rendered-hash",
        ),
        response_schema={
            "type": "object",
            "properties": {"moments": {"type": "array"}},
            "required": ["moments"],
        },
        generation=GenerationParameters(
            temperature=0.1,
            max_output_tokens=512,
            top_p=0.9,
        ),
    )


def sdk_response() -> object:
    response_body = {
        "moments": [
            {
                "candidate_id": "scene-1",
                "title": "A title",
                "description": "A description",
                "hashtags": ["MomentAI"],
                "explanation": "An explanation",
                "category": {
                    "category_id": "education",
                    "label": "Education",
                    "confidence": 0.8,
                },
                "viral_potential": {
                    "score": 0.6,
                    "confidence": 0.7,
                    "rationale": "Clear hook.",
                    "limitations": "No audience data.",
                },
            }
        ]
    }
    return SimpleNamespace(
        text=json.dumps(response_body),
        response_id="gemini-response-1",
        usage_metadata=SimpleNamespace(
            prompt_token_count=120,
            candidates_token_count=80,
        ),
        candidates=(SimpleNamespace(finish_reason=SimpleNamespace(name="STOP")),),
    )


class GeminiProviderTests(unittest.IsolatedAsyncioTestCase):
    def test_construction_uses_configuration_and_official_client_factory(self) -> None:
        config = provider_config()
        fake_client = FakeClient(FakeModels(sdk_response()))
        client_factory = Mock(return_value=fake_client)
        fake_genai = ModuleType("google.genai")
        fake_genai.Client = client_factory
        fake_google = ModuleType("google")
        fake_google.genai = fake_genai

        with patch.dict(
            sys.modules,
            {"google": fake_google, "google.genai": fake_genai},
        ):
            provider = GeminiProvider(config)

        client_factory.assert_called_once_with(
            api_key="configuration-supplied-test-key",
            http_options={
                "timeout": 5000.0,
                "retry_options": {
                    "attempts": 4,
                    "initial_delay": 1.0,
                    "max_delay": 30.0,
                    "exp_base": 2.0,
                    "jitter": 0.1,
                    "http_status_codes": [408, 429, 500, 502, 503, 504],
                },
            },
        )
        self.assertNotIn("configuration-supplied-test-key", repr(config))
        self.assertEqual(provider.metadata.provider_id, "gemini")
        self.assertTrue(provider.metadata.supports_structured_output)
        self.assertTrue(provider.supports("structured_json"))

    def test_registry_registers_and_resolves_gemini(self) -> None:
        provider = GeminiProvider(
            provider_config(),
            client=FakeClient(FakeModels(sdk_response())),
        )
        registry = ProviderRegistry((provider,))

        self.assertTrue(registry.is_registered("gemini"))
        self.assertEqual(registry.provider_ids, ("gemini",))
        self.assertIs(registry.resolve("gemini"), provider)

    async def test_structured_request_and_response_diagnostics(self) -> None:
        models = FakeModels(sdk_response())
        diagnostics = []
        provider = GeminiProvider(
            provider_config(),
            client=FakeClient(models),
            diagnostic_sink=diagnostics.append,
        )

        response = await provider.generate_batch(batch_request())

        self.assertEqual(len(models.calls), 1)
        call = models.calls[0]
        self.assertEqual(call["model"], "gemini-test-model")
        self.assertEqual(
            call["contents"],
            "Rendered user content supplied by the prompt layer.",
        )
        generation_config = call["config"]
        self.assertEqual(generation_config["response_mime_type"], "application/json")
        self.assertEqual(generation_config["max_output_tokens"], 512)
        self.assertEqual(
            generation_config["safety_settings"][0]["threshold"],
            "BLOCK_ONLY_HIGH",
        )
        self.assertEqual(response.outputs[0].candidate_id, "scene-1")
        self.assertEqual(response.provider_request_id, "gemini-response-1")
        self.assertEqual(response.token_usage.input_tokens, 120)
        self.assertEqual(response.token_usage.output_tokens, 80)
        self.assertIs(response.finish_reason, ProviderFinishReason.STOP)
        self.assertEqual(diagnostics[0].request_id, "semantic-request-1")
        self.assertEqual(diagnostics[0].status, "succeeded")

    async def test_timeout_is_provider_neutral_and_diagnostic(self) -> None:
        diagnostics = []
        provider = GeminiProvider(
            provider_config(timeout_seconds=0.01),
            client=FakeClient(BlockingModels()),
            diagnostic_sink=diagnostics.append,
        )

        with self.assertRaises(ProviderTimeoutError):
            await provider.generate_batch(batch_request())

        self.assertEqual(diagnostics[0].status, "timed_out")
        self.assertTrue(diagnostics[0].retryable)


if __name__ == "__main__":
    unittest.main()
