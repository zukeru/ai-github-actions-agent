import os
import sys
import unittest
from unittest import mock


DOCKER_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    ".github",
    "actions",
    "gha-agent-review",
    "docker",
)
sys.path.insert(0, DOCKER_DIR)

from gha_agent_review_agent import providers  # noqa: E402


class ProviderTests(unittest.TestCase):
    def test_auto_prefers_azure_when_endpoint_and_key_exist(self):
        config = providers.resolve_provider(
            provider="auto",
            model_id="review-deployment",
            aws_region="",
            azure_openai_endpoint="",
            azure_openai_api_version="",
            env={
                "AZURE_OPENAI_API_KEY": "key",
                "AZURE_OPENAI_ENDPOINT": "https://example.openai.azure.com",
                "OPENAI_API_KEY": "openai-key",
            },
        )

        self.assertEqual(config.provider, "azure-openai")
        self.assertEqual(config.model_id, "review-deployment")

    def test_explicit_azure_allows_management_setup_without_data_plane_values(self):
        config = providers.resolve_provider(
            provider="azure-openai",
            model_id="review-deployment",
            aws_region="",
            azure_openai_endpoint="",
            azure_openai_api_version="",
            env={
                "AZURE_ACCESS_TOKEN": "token",
                "AZURE_SUBSCRIPTION_ID": "sub",
                "AZURE_RESOURCE_GROUP": "rg",
                "AZURE_OPENAI_ACCOUNT_NAME": "acct",
            },
        )

        self.assertEqual(config.provider, "azure-openai")
        self.assertEqual(config.azure_openai_api_key, "")
        self.assertEqual(config.azure_openai_endpoint, "")

    def test_auto_uses_azure_when_management_setup_values_exist(self):
        config = providers.resolve_provider(
            provider="auto",
            model_id="review-deployment",
            aws_region="",
            azure_openai_endpoint="",
            azure_openai_api_version="",
            env={
                "AZURE_ACCESS_TOKEN": "token",
                "AZURE_SUBSCRIPTION_ID": "sub",
                "AZURE_RESOURCE_GROUP": "rg",
                "AZURE_OPENAI_ACCOUNT_NAME": "acct",
            },
        )

        self.assertEqual(config.provider, "azure-openai")

    def test_auto_uses_openai_when_openai_key_exists(self):
        config = providers.resolve_provider(
            provider="auto",
            model_id="",
            aws_region="",
            azure_openai_endpoint="",
            azure_openai_api_version="",
            env={
                "OPENAI_API_KEY": "key",
                "OPENAI_MODEL_ID": "gpt-review",
                "BEDROCK_MODEL_ID": "bedrock-review",
            },
        )

        self.assertEqual(config.provider, "openai")
        self.assertEqual(config.model_id, "gpt-review")
        self.assertEqual(config.openai_api_key, "key")

    def test_explicit_anthropic_accepts_gha_claude_api_key_alias(self):
        config = providers.resolve_provider(
            provider="anthropic",
            model_id="",
            aws_region="",
            azure_openai_endpoint="",
            azure_openai_api_version="",
            env={
                "GHA_AI_AGENT_CLAUDE_API_KEY": "key",
                "CLAUDE_MODEL_ID": "claude-review",
            },
        )

        self.assertEqual(config.provider, "anthropic")
        self.assertEqual(config.model_id, "claude-review")
        self.assertEqual(config.anthropic_api_key, "key")

    def test_explicit_anthropic_accepts_claude_api_key_alias(self):
        config = providers.resolve_provider(
            provider="claude",
            model_id="claude-review",
            aws_region="",
            azure_openai_endpoint="",
            azure_openai_api_version="",
            env={"CLAUDE_API_KEY": "key"},
        )

        self.assertEqual(config.provider, "anthropic")
        self.assertEqual(config.anthropic_api_key, "key")

    def test_explicit_google_accepts_gemini_key_alias(self):
        config = providers.resolve_provider(
            provider="gemini",
            model_id="gemini-review",
            aws_region="",
            azure_openai_endpoint="",
            azure_openai_api_version="",
            env={"GEMINI_API_KEY": "key"},
        )

        self.assertEqual(config.provider, "google")
        self.assertEqual(config.google_api_key, "key")

    def test_openai_response_text_falls_back_to_output_parts(self):
        text = providers.response_text_from_openai(
            {
                "output": [
                    {
                        "content": [
                            {"type": "output_text", "text": "{\"summary\":\"ok\"}"},
                        ]
                    }
                ]
            }
        )

        self.assertEqual(text, "{\"summary\":\"ok\"}")

    def test_azure_invocation_uses_deployment_endpoint(self):
        config = providers.ProviderConfig(
            provider="azure-openai",
            model_id="review deployment",
            azure_openai_api_key="key",
            azure_openai_endpoint="https://example.openai.azure.com/",
            azure_openai_api_version="2024-10-21",
        )

        with mock.patch.object(providers, "post_json") as post_json:
            post_json.return_value = {"choices": [{"message": {"content": "ok"}}]}
            self.assertEqual(providers.invoke_azure_openai(config, "prompt", 12), "ok")

        url = post_json.call_args.args[0]
        self.assertIn("/openai/deployments/review%20deployment/chat/completions", url)
        self.assertIn("api-version=2024-10-21", url)


if __name__ == "__main__":
    unittest.main()
