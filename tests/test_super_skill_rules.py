import os
import sys
import unittest


REPO_ROOT = os.path.dirname(os.path.dirname(__file__))
SCRIPTS_DIR = os.path.join(REPO_ROOT, ".github", "actions", "gha-agent-review", "scripts")
sys.path.insert(0, SCRIPTS_DIR)

from review_common import build_review_body, normalize_review_result  # noqa: E402
from super_skill_rules import (  # noqa: E402
    apply_super_skill_mapping,
    build_super_skill_prompt_context,
)


def fixture_catalog():
    return {
        "catalog_version": 1,
        "source_count": 2,
        "rule_count": 3,
        "official_best_practice_rules": [
            {
                "id": "official.react.dangerous-html",
                "category": "react",
                "title": "Treat dangerouslySetInnerHTML as an XSS-sensitive DOM sink",
                "source_url": "https://react.dev/reference/react-dom/components/common#dangerously-setting-the-inner-html",
                "keywords": ["react", "dangerouslysetinnerhtml", "xss", "html", "sanitize"],
            }
        ],
        "rules": [
            {
                "id": "skill.code-quality.code-review-and-quality",
                "category": "code-quality",
                "source": "code-review-and-quality",
                "title": "Review maintainability, tests, and production risk",
                "keywords": ["review", "maintainability", "quality", "tests"],
            },
            {
                "id": "skill.github-actions.using-git-worktrees",
                "category": "git",
                "source": "using-git-worktrees",
                "title": "Keep branch and PR workflows isolated",
                "keywords": ["git", "branch", "worktree", "pull", "request"],
            },
        ],
    }


class SuperSkillRulesTests(unittest.TestCase):
    def test_prompt_context_selects_relevant_rules_for_changed_surfaces(self):
        context = {
            "files": [
                {"filename": "src/App.tsx"},
                {"filename": ".github/workflows/review.yml"},
            ],
            "file_contents": {
                "src/App.tsx": "return <div dangerouslySetInnerHTML={{ __html: userHtml }} />",
                ".github/workflows/review.yml": "name: review\npermissions: write-all\n",
            },
        }

        prompt_context = build_super_skill_prompt_context(
            fixture_catalog(),
            context,
            enabled=True,
            max_rules=5,
        )

        rule_ids = {rule["id"] for rule in prompt_context["rules"]}
        self.assertTrue(prompt_context["enabled"])
        self.assertIn("official.react.dangerous-html", rule_ids)
        self.assertTrue(prompt_context["category_counts"])

    def test_mapping_adds_rule_ids_sources_and_category_counts(self):
        result = {
            "findings": [
                {
                    "path": "src/App.tsx",
                    "line": 10,
                    "severity": "high",
                    "blocks_merge": True,
                    "rule_id": "security.xss",
                    "title": "Sanitize untrusted HTML",
                    "body": "React dangerouslySetInnerHTML renders untrusted html and creates an XSS path.",
                }
            ]
        }

        mapped = apply_super_skill_mapping(result, fixture_catalog())
        finding = mapped["findings"][0]
        categories = mapped["super_skill_summary"]["categories"]

        self.assertIn("official.react.dangerous-html", finding["best_practice_rule_ids"])
        self.assertIn("https://react.dev/reference/react-dom/components/common#dangerously-setting-the-inner-html", finding["super_skill_sources"])
        react_summary = [item for item in categories if item["category"] == "react"][0]
        self.assertEqual(react_summary["violations"], 1)
        self.assertEqual(react_summary["blocking"], 1)

    def test_review_body_renders_super_skill_coverage(self):
        normalized = normalize_review_result(
            {
                "summary": "Review found a React XSS issue.",
                "outcome": "fail",
                "findings": [
                    {
                        "path": "src/App.tsx",
                        "line": 10,
                        "severity": "high",
                        "blocks_merge": True,
                        "rule_id": "security.xss",
                        "title": "Sanitize untrusted HTML",
                        "body": "React dangerouslySetInnerHTML renders untrusted html and creates an XSS path.",
                        "best_practice_rule_ids": ["official.react.dangerous-html"],
                        "super_skill_sources": ["react-docs"],
                    }
                ],
            }
        )
        mapped = apply_super_skill_mapping(normalized, fixture_catalog())

        body = build_review_body(mapped, 0, [], 25, history={})

        self.assertIn("### Super Skill Rule Coverage", body)
        self.assertIn("`react`", body)
        self.assertIn("official.react.dangerous-html", body)


if __name__ == "__main__":
    unittest.main()
