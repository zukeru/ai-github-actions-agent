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

from gha_agent_review_agent import bootstrap  # noqa: E402


class BootstrapSetupTests(unittest.TestCase):
    def test_google_setup_reuses_existing_marker_file(self):
        config = mock.Mock(google_api_key="google-key")
        with mock.patch.object(bootstrap, "request_json") as request_json:
            request_json.return_value = {
                "files": [
                    {
                        "name": "files/existing",
                        "displayName": "gha-agent-review",
                    }
                ]
            }

            result = bootstrap.ensure_google_marker(config, "gha-agent-review")

        self.assertEqual(result["status"], "found")
        self.assertEqual(result["marker"]["name"], "files/existing")
        self.assertEqual(request_json.call_count, 1)

    def test_google_setup_creates_marker_file_when_missing(self):
        config = mock.Mock(google_api_key="google-key")
        with mock.patch.object(bootstrap, "request_json") as request_json:
            request_json.side_effect = [
                {"files": []},
                {"file": {"name": "files/new-marker", "displayName": "gha-agent-review"}},
            ]

            result = bootstrap.ensure_google_marker(config, "gha-agent-review")

        self.assertEqual(result["status"], "created")
        create_payload = request_json.call_args_list[1].args[3]
        self.assertEqual(create_payload["file"]["displayName"], "gha-agent-review")
        self.assertEqual(create_payload["file"]["name"], "files/gha-agent-review")

    def test_azure_setup_creates_account_and_deployment_with_tags(self):
        config = mock.Mock(
            model_id="review-deployment",
            azure_openai_api_key="",
            azure_openai_endpoint="https://acct.openai.azure.com",
            azure_openai_api_version="2024-10-21",
        )
        options = bootstrap.AzureSetupOptions(
            access_token="token",
            subscription_id="sub",
            resource_group="rg",
            account_name="acct",
            location="eastus",
            account_sku="S0",
            deployment_model_name="gpt-4o-mini",
            deployment_model_version="2024-07-18",
            deployment_sku_name="Standard",
            deployment_capacity=1,
        )

        def fake_request(method, url, headers, payload=None, allowed_statuses=(200,)):
            if method == "GET" and url.endswith("/accounts/acct?api-version=2024-10-01"):
                raise bootstrap.HttpStatusError(404, url, "missing")
            if method == "PUT" and url.endswith("/accounts/acct?api-version=2024-10-01"):
                return {"name": "acct", "tags": payload["tags"]}
            if method == "GET" and "/deployments/review-deployment?" in url:
                raise bootstrap.HttpStatusError(404, url, "missing")
            if method == "PUT" and "/deployments/review-deployment?" in url:
                return {"name": "review-deployment", "tags": payload["tags"]}
            if method == "POST" and url.endswith("/accounts/acct/listKeys?api-version=2024-10-01"):
                return {"key1": "generated-key"}
            raise AssertionError(f"unexpected request {method} {url}")

        with mock.patch.object(bootstrap, "request_json", side_effect=fake_request):
            result = bootstrap.ensure_azure_setup(config, options, "gha-agent-review")

        self.assertEqual(result["status"], "created")
        self.assertEqual(result["account"]["tags"]["purpose"], "gha-agent-review")
        self.assertEqual(result["deployment"]["tags"]["managed-by"], "github-actions")
        self.assertEqual(result["runtime_env"]["AZURE_OPENAI_ENDPOINT"], "https://acct.openai.azure.com")
        self.assertEqual(result["runtime_env"]["AZURE_OPENAI_API_KEY"], "generated-key")


if __name__ == "__main__":
    unittest.main()
