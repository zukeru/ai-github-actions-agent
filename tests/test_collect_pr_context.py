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

from collect_pr_context import github_blob_to_contents_url, should_capture_text_content  # noqa: E402


class CollectPrContextTests(unittest.TestCase):
    def test_converts_github_blob_url_to_contents_url(self):
        url = github_blob_to_contents_url("https://github.com/example-org/gha-agent-review/blob/main/.claude/rules.md")
        self.assertEqual(
            url,
            "https://api.github.com/repos/example-org/gha-agent-review/contents/.claude/rules.md?ref=main",
        )

    def test_leaves_non_blob_url_unchanged(self):
        url = "https://raw.githubusercontent.com/example-org/gha-agent-review/main/.claude/rules.md"
        self.assertEqual(github_blob_to_contents_url(url), url)

    def test_captures_common_review_context_files(self):
        self.assertTrue(should_capture_text_content("README.md"))
        self.assertTrue(should_capture_text_content("docs/architecture.md"))
        self.assertTrue(should_capture_text_content("coverage/coverage-summary.json"))
        self.assertTrue(should_capture_text_content("pyproject.toml"))
        self.assertFalse(should_capture_text_content("dist/app.bin"))


if __name__ == "__main__":
    unittest.main()
