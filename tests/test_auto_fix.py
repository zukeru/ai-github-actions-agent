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

import auto_fix  # noqa: E402
from auto_fix import (  # noqa: E402
    add_architecture_docs_if_missing,
    add_readme_mermaid_if_missing,
    apply_safe_finding_fixes,
    build_fix_branch_name,
    is_agent_fix_branch,
    run_auto_fix,
)


class AutoFixTests(unittest.TestCase):
    def test_build_fix_branch_name_sanitizes_source_branch(self):
        self.assertEqual(
            build_fix_branch_name("feature/add auth", "abcdef1234567890"),
            "feature-add-auth-agent-fixes-abcdef1",
        )

    def test_agent_fix_branch_is_skipped(self):
        self.assertTrue(is_agent_fix_branch("feature-agent-fixes-abcdef1"))
        self.assertFalse(is_agent_fix_branch("feature-auth"))

    def test_apply_safe_line_replacement_requires_auto_fix(self):
        contents = {"app.py": "token = old\nprint(token)\n"}
        findings = [
            {
                "path": "app.py",
                "line": 1,
                "source_line": "token = old",
                "suggestion": "token = new",
                "auto_fix": True,
            },
            {
                "path": "app.py",
                "line": 2,
                "source_line": "print(token)",
                "suggestion": "print('hidden')",
                "auto_fix": False,
            },
        ]

        updated, count = apply_safe_finding_fixes(contents, findings, max_findings=10, max_files=10)

        self.assertEqual(count, 1)
        self.assertEqual(updated["app.py"], "token = new\nprint(token)\n")

    def test_add_readme_mermaid_only_when_absent(self):
        updated, added = add_readme_mermaid_if_missing(
            {"README.md": "# Service\n\nOverview.\n"},
            "example-org/service",
            enabled=True,
        )

        self.assertTrue(added)
        self.assertIn("```mermaid", updated["README.md"])
        self.assertIn("example-org/service", updated["README.md"])

        unchanged, added_again = add_readme_mermaid_if_missing(updated, "example-org/service", enabled=True)
        self.assertFalse(added_again)
        self.assertEqual(unchanged, updated)

    def test_add_architecture_docs_only_when_absent(self):
        updated, added = add_architecture_docs_if_missing(
            {"README.md": "# Service\n"},
            "example-org/service",
            {"head_tree_paths": [".github/workflows/build.yml", "Dockerfile", "package.json"]},
            enabled=True,
        )

        self.assertTrue(added)
        self.assertIn("docs/architecture.md", updated)
        self.assertIn("```mermaid", updated["docs/architecture.md"])
        self.assertIn("example-org/service Architecture", updated["docs/architecture.md"])
        self.assertIn(".github/workflows/build.yml", updated["docs/architecture.md"])

        unchanged, added_again = add_architecture_docs_if_missing(
            updated,
            "example-org/service",
            {"head_tree_paths": ["docs/architecture.md"]},
            enabled=True,
        )
        self.assertFalse(added_again)
        self.assertEqual(unchanged, updated)

    def test_run_auto_fix_skips_existing_fix_branch(self):
        result = run_auto_fix(
            token="token",
            repository="example-org/service",
            context={
                "pr": {
                    "head_ref": "feature-agent-fixes-abcdef1",
                    "head_sha": "abcdef1234567890",
                    "head_repo": "example-org/service",
                },
                "file_contents": {"README.md": "# Service\n"},
            },
            result={"findings": []},
            enabled=True,
            add_readme_diagrams=True,
            add_architecture_docs=True,
            max_findings=10,
            max_files=10,
        )

        self.assertEqual(result["status"], "skipped")
        self.assertIn("already an agent fix branch", result["message"])

    def test_run_auto_fix_creates_branch_commit_and_pr(self):
        calls = []

        def fake_create(**kwargs):
            calls.append(kwargs)
            return "https://github.com/example-org/service/pull/2"

        original = auto_fix.create_fix_branch_commit_and_pr
        auto_fix.create_fix_branch_commit_and_pr = fake_create
        try:
            result = run_auto_fix(
                token="token",
                repository="example-org/service",
                context={
                    "pr": {
                        "head_ref": "feature/auth",
                        "head_sha": "abcdef1234567890",
                        "head_repo": "example-org/service",
                    },
                    "file_contents": {
                        "README.md": "# Service\n",
                        "app.py": "flag = True\n",
                    },
                    "head_tree_paths": [".github/workflows/build.yml", "package.json"],
                },
                result={
                    "findings": [
                        {
                            "path": "app.py",
                            "line": 1,
                            "source_line": "flag = True",
                            "suggestion": "flag = False",
                            "auto_fix": True,
                        }
                    ]
                },
                enabled=True,
                add_readme_diagrams=True,
                add_architecture_docs=True,
                max_findings=10,
                max_files=10,
            )
        finally:
            auto_fix.create_fix_branch_commit_and_pr = original

        self.assertEqual(result["status"], "created")
        self.assertEqual(result["fix_branch"], "feature-auth-agent-fixes-abcdef1")
        self.assertEqual(result["fix_pr_url"], "https://github.com/example-org/service/pull/2")
        self.assertEqual(calls[0]["source_branch"], "feature/auth")
        self.assertIn("app.py", calls[0]["modified_files"])
        self.assertIn("README.md", calls[0]["modified_files"])
        self.assertIn("docs/architecture.md", calls[0]["modified_files"])
        self.assertTrue(result["architecture_doc_added"])


if __name__ == "__main__":
    unittest.main()
