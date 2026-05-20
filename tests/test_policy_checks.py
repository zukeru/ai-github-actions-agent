import os
import sys
import unittest


SCRIPTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    ".github",
    "actions",
    "gha-agent-review",
    "scripts",
)
sys.path.insert(0, SCRIPTS_DIR)

from policy_checks import evaluate_policy  # noqa: E402
from review_common import normalize_review_result, split_blocking_and_warnings  # noqa: E402


class PolicyChecksTests(unittest.TestCase):
    def normalized(self, context):
        return normalize_review_result({"summary": "ok", "findings": evaluate_policy(context)})

    def test_custom_runner_is_warning_only(self):
        context = {
            "repository": "example-org/service",
            "file_contents": {
                ".github/workflows/deploy.yml": "jobs:\n  deploy:\n    runs-on: [self-hosted, linux]\n"
            },
        }

        result = self.normalized(context)
        blocking, warnings = split_blocking_and_warnings(result["findings"])

        self.assertEqual(blocking, [])
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0]["warning_type"], "public-runner")
        self.assertEqual(result["outcome"], "pass")

    def test_gha_agent_token_fix_is_auto_fixable(self):
        context = {
            "repository": "example-org/service",
            "file_contents": {
                ".github/workflows/gha-agent-review.yml": (
                    "steps:\n"
                    "  - uses: zukeru/ai-github-actions-agent/.github/actions/gha-agent-review@main\n"
                    "    with:\n"
                    "      github-token: \"${{ github.token }}\"\n"
                )
            },
        }

        result = self.normalized(context)
        blocking, _warnings = split_blocking_and_warnings(result["findings"])

        self.assertEqual(len(blocking), 1)
        self.assertEqual(blocking[0]["rule_id"], "github-actions.git-token")
        self.assertTrue(blocking[0]["auto_fix"])
        self.assertIn("GHA_AI_AGENT_GIT_TOKEN", blocking[0]["suggestion"])

    def test_self_test_token_exception_is_allowed(self):
        context = {
            "repository": "zukeru/ai-github-actions-agent",
            "file_contents": {
                ".github/workflows/gha-agent-review.yml": (
                    "steps:\n"
                    "  - uses: ./.github/actions/gha-agent-review\n"
                    "    with:\n"
                    "      github-token: \"${{ secrets.GITHUB_TOKEN_NOT_OEPNER || secrets.GHA_AI_AGENT_GIT_TOKEN }}\"\n"
                )
            },
        }

        self.assertEqual(evaluate_policy(context), [])

    def test_floating_action_ref_blocks(self):
        context = {
            "repository": "example-org/service",
            "file_contents": {
                ".github/workflows/build.yml": "steps:\n  - uses: third-party/action@main\n"
            },
        }

        result = self.normalized(context)
        blocking, _warnings = split_blocking_and_warnings(result["findings"])

        self.assertEqual(len(blocking), 1)
        self.assertEqual(blocking[0]["rule_id"], "github-actions.action-ref.floating")

    def test_dockerfile_latest_and_root_are_warnings(self):
        context = {
            "repository": "example-org/service",
            "file_contents": {
                "Dockerfile": "FROM python:latest\nCOPY . /app\n"
            },
        }

        result = self.normalized(context)
        blocking, warnings = split_blocking_and_warnings(result["findings"])
        rule_ids = {item["rule_id"] for item in warnings}

        self.assertEqual(blocking, [])
        self.assertIn("docker.base.latest", rule_ids)
        self.assertIn("docker.non-root-user", rule_ids)

    def test_kubernetes_privileged_blocks_and_can_auto_fix(self):
        context = {
            "repository": "example-org/service",
            "file_contents": {
                "k8s/deploy.yml": (
                    "apiVersion: apps/v1\n"
                    "kind: Deployment\n"
                    "spec:\n"
                    "  template:\n"
                    "    spec:\n"
                    "      containers:\n"
                    "        - securityContext:\n"
                    "            privileged: true\n"
                )
            },
        }

        result = self.normalized(context)
        blocking, _warnings = split_blocking_and_warnings(result["findings"])

        self.assertEqual(len(blocking), 1)
        self.assertEqual(blocking[0]["rule_id"], "kubernetes.pod-security.privileged")
        self.assertTrue(blocking[0]["auto_fix"])
        self.assertIn("privileged: false", blocking[0]["suggestion"])

    def test_iac_public_management_and_wildcard_iam_block(self):
        context = {
            "repository": "example-org/service",
            "file_contents": {
                "infra/main.tf": (
                    'resource "aws_security_group_rule" "ssh" {\n'
                    '  cidr_blocks = ["0.0.0.0/0"]\n'
                    '  from_port = 22\n'
                    '}\n'
                    'resource "aws_iam_policy" "admin" {\n'
                    '  policy = "{\\"Action\\": \\"*\\", \\"Resource\\": \\"*\\"}"\n'
                    '}\n'
                )
            },
        }

        result = self.normalized(context)
        blocking, _warnings = split_blocking_and_warnings(result["findings"])
        rule_ids = {item["rule_id"] for item in blocking}

        self.assertIn("iac.network.public-management", rule_ids)
        self.assertIn("iac.iam.wildcard", rule_ids)

    def test_package_manifest_without_lockfile_warns(self):
        context = {
            "repository": "example-org/service",
            "files": [{"filename": "package.json"}],
            "head_tree_paths": ["package.json"],
            "file_contents": {
                "package.json": '{"dependencies": {"left-pad": "^1.3.0"}}'
            },
        }

        result = self.normalized(context)
        blocking, warnings = split_blocking_and_warnings(result["findings"])

        self.assertEqual(blocking, [])
        self.assertTrue(any(item["rule_id"] == "packages.lockfile.missing" for item in warnings))

    def test_coverage_below_ninety_warns(self):
        context = {
            "repository": "example-org/service",
            "coverage_warning_threshold": 90,
            "file_contents": {
                "coverage/coverage-summary.json": '{"total": {"lines": {"pct": 87.5}}}'
            },
        }

        result = self.normalized(context)
        blocking, warnings = split_blocking_and_warnings(result["findings"])

        self.assertEqual(blocking, [])
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0]["warning_type"], "coverage")

    def test_readme_without_mermaid_warns(self):
        context = {
            "repository": "example-org/service",
            "file_contents": {
                "README.md": "# Service\n\nNo diagram yet.\n"
            },
        }

        result = self.normalized(context)
        blocking, warnings = split_blocking_and_warnings(result["findings"])

        self.assertEqual(blocking, [])
        self.assertTrue(any(item["rule_id"] == "documentation.readme.mermaid" for item in warnings))
        self.assertTrue(any(item["rule_id"] == "documentation.architecture.missing" for item in warnings))

    def test_architecture_doc_with_mermaid_satisfies_documentation_rule(self):
        context = {
            "repository": "example-org/service",
            "head_tree_paths": ["README.md", "docs/architecture.md"],
            "file_contents": {
                "README.md": "# Service\n\n```mermaid\nflowchart LR\n  a --> b\n```\n",
                "docs/architecture.md": "# Architecture\n\n```mermaid\nflowchart TD\n  app --> db\n```\n",
            },
        }

        result = self.normalized(context)
        _blocking, warnings = split_blocking_and_warnings(result["findings"])

        self.assertFalse(any(item["rule_id"].startswith("documentation.") for item in warnings))

    def test_architecture_doc_without_mermaid_warns(self):
        context = {
            "repository": "example-org/service",
            "head_tree_paths": ["docs/architecture.md"],
            "file_contents": {
                "docs/architecture.md": "# Architecture\n\nText only.\n",
            },
        }

        result = self.normalized(context)
        _blocking, warnings = split_blocking_and_warnings(result["findings"])

        self.assertTrue(any(item["rule_id"] == "documentation.architecture.mermaid" for item in warnings))

    def test_compliance_warning_type_is_non_blocking(self):
        result = normalize_review_result(
            {
                "summary": "advisory",
                "outcome": "fail",
                "findings": [
                    {
                        "path": ".github/workflows/deploy.yml",
                        "line": 12,
                        "severity": "medium",
                        "blocks_merge": False,
                        "warning_type": "compliance",
                        "title": "Compliance advisory",
                        "body": "Document the exception before merge.",
                    }
                ],
            }
        )
        blocking, warnings = split_blocking_and_warnings(result["findings"])

        self.assertEqual(blocking, [])
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0]["warning_type"], "compliance")
        self.assertEqual(result["outcome"], "pass")


if __name__ == "__main__":
    unittest.main()
