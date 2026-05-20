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

import post_review  # noqa: E402
from post_review import split_inline_findings  # noqa: E402
from review_common import (  # noqa: E402
    build_review_body,
    finding_to_comment_body,
    marker_payload_from_body,
    normalize_review_result,
    split_blocking_and_warnings,
)


class PostReviewTests(unittest.TestCase):
    def test_normalizes_pass_result(self):
        result = normalize_review_result({"summary": "ok", "outcome": "pass", "findings": []})
        self.assertEqual(result["outcome"], "pass")
        self.assertEqual(result["findings"], [])

    def test_findings_force_fail(self):
        result = normalize_review_result(
            {
                "summary": "needs work",
                "outcome": "pass",
                "findings": [
                    {
                        "path": "app.py",
                        "line": 3,
                        "title": "Missing validation",
                        "body": "Validate the input before use.",
                    }
                ],
            }
        )
        self.assertEqual(result["outcome"], "fail")

    def test_warning_findings_do_not_force_fail(self):
        result = normalize_review_result(
            {
                "summary": "warnings only",
                "outcome": "fail",
                "findings": [
                    {
                        "path": ".github/workflows/deploy.yml",
                        "line": 9,
                        "severity": "medium",
                        "blocks_merge": False,
                        "warning_type": "public-runner",
                        "title": "Custom runner",
                        "body": "Use a public GitHub runner unless this exception is approved.",
                    }
                ],
            }
        )
        blocking, warnings = split_blocking_and_warnings(result["findings"])
        self.assertEqual(result["outcome"], "pass")
        self.assertEqual(blocking, [])
        self.assertEqual(len(warnings), 1)

    def test_optional_model_warnings_are_dropped(self):
        result = normalize_review_result(
            {
                "summary": "optional warning",
                "outcome": "pass",
                "findings": [
                    {
                        "path": "app.py",
                        "line": 10,
                        "severity": "medium",
                        "blocks_merge": False,
                        "warning_type": "optional",
                        "title": "Possible cleanup",
                        "body": "Consider a nice-to-have cleanup.",
                    }
                ],
            }
        )

        self.assertEqual(result["outcome"], "pass")
        self.assertEqual(result["findings"], [])

    def test_splits_inline_and_summary_findings(self):
        findings = [
            {"path": "app.py", "line": 3, "title": "Inline", "body": "Inline body"},
            {"path": "app.py", "line": 8, "title": "Summary", "body": "Summary body"},
            {"path": None, "line": None, "title": "General", "body": "General body"},
        ]
        inline, summary = split_inline_findings(findings, {"app.py": {3}}, 25)
        self.assertEqual([item["title"] for item in inline], ["Inline"])
        self.assertEqual([item["title"] for item in summary], ["Summary", "General"])

    def test_respects_inline_limit(self):
        findings = [
            {"path": "app.py", "line": 3, "title": "First", "body": "First body"},
            {"path": "app.py", "line": 4, "title": "Second", "body": "Second body"},
        ]
        inline, summary = split_inline_findings(findings, {"app.py": {3, 4}}, 1)
        self.assertEqual([item["title"] for item in inline], ["First"])
        self.assertEqual([item["title"] for item in summary], ["Second"])

    def test_submit_review_includes_commit_id(self):
        captured = {}

        def fake_post(path, token, payload):
            captured["path"] = path
            captured["token"] = token
            captured["payload"] = payload
            return {}

        original = post_review.github_post
        post_review.github_post = fake_post
        try:
            post_review.submit_review(
                "token",
                "example-org/gha-agent-review",
                12,
                "APPROVE",
                "body",
                [
                    {
                        "path": "app.py",
                        "line": 12,
                        "body": "Inline warning body",
                    }
                ],
                "abc123",
            )
        finally:
            post_review.github_post = original

        self.assertEqual(captured["payload"]["commit_id"], "abc123")
        self.assertEqual(captured["payload"]["event"], "APPROVE")

    def test_request_changes_on_own_pr_falls_back_to_issue_comment(self):
        calls = []

        def fake_post(path, token, payload):
            calls.append((path, payload))
            if path.endswith("/pulls/12/reviews"):
                raise post_review.GitHubApiError(
                    422,
                    path,
                    '{"errors":["Review Can not request changes on your own pull request"]}',
                )
            return {}

        original = post_review.github_post
        post_review.github_post = fake_post
        try:
            post_review.submit_review(
                "token",
                "example-org/gha-agent-review",
                12,
                "REQUEST_CHANGES",
                "body",
                [
                    {
                        "path": "app.py",
                        "line": 12,
                        "body": "Inline finding body",
                    }
                ],
                "abc123",
            )
        finally:
            post_review.github_post = original

        self.assertEqual(calls[0][0], "/repos/example-org/gha-agent-review/pulls/12/reviews")
        self.assertEqual(calls[1][0], "/repos/example-org/gha-agent-review/issues/12/comments")
        self.assertIn("app.py:12", calls[1][1]["body"])
        self.assertIn("Inline finding body", calls[1][1]["body"])
        self.assertIn("workflow still failed", calls[1][1]["body"])

    def test_approve_on_own_pr_falls_back_to_passing_issue_comment(self):
        calls = []

        def fake_post(path, token, payload):
            calls.append((path, payload))
            if path.endswith("/pulls/12/reviews"):
                raise post_review.GitHubApiError(
                    422,
                    path,
                    '{"errors":["Review Can not approve your own pull request"]}',
                )
            return {}

        original = post_review.github_post
        post_review.github_post = fake_post
        try:
            post_review.submit_review(
                "token",
                "example-org/gha-agent-review",
                12,
                "APPROVE",
                "body",
                [
                    {
                        "path": "app.py",
                        "line": 12,
                        "body": "Inline warning body",
                    }
                ],
                "abc123",
            )
        finally:
            post_review.github_post = original

        self.assertEqual(calls[0][0], "/repos/example-org/gha-agent-review/pulls/12/reviews")
        self.assertEqual(calls[1][0], "/repos/example-org/gha-agent-review/issues/12/comments")
        self.assertIn("app.py:12", calls[1][1]["body"])
        self.assertIn("Inline warning body", calls[1][1]["body"])
        self.assertIn("workflow still passed", calls[1][1]["body"])

    def test_comment_body_cites_line_and_recommendation(self):
        body = finding_to_comment_body(
            {
                "path": "app.py",
                "line": 20,
                "severity": "critical",
                "rule_id": "security",
                "title": "SQL injection",
                "body": "User input is interpolated into SQL.",
                "suggestion": "rows = db.execute(query, (name,)).fetchall()",
                "source_line": "query = f\"SELECT * FROM users WHERE name = '{name}'\"",
            }
        )

        self.assertIn("severity-critical", body)
        self.assertIn("**Location:** `app.py:20`", body)
        self.assertIn("20 | query = f", body)
        self.assertIn("**Recommended change**", body)
        self.assertIn("```suggestion", body)

    def test_review_body_includes_severity_legend(self):
        body = build_review_body(
            {"summary": "summary", "outcome": "fail", "findings": []},
            0,
            [],
            25,
        )

        self.assertIn("### Severity Legend", body)
        self.assertIn("severity-critical", body)
        self.assertIn("Merge guidance", body)

    def test_review_body_includes_auto_fix_status(self):
        body = build_review_body(
            {
                "summary": "summary",
                "outcome": "fail",
                "findings": [],
                "auto_fix": {
                    "status": "created",
                    "fix_branch": "feature-agent-fixes-abcdef1",
                    "fix_pr_url": "https://github.com/example/repo/pull/2",
                    "fix_count": 1,
                    "diagram_added": True,
                    "architecture_doc_added": True,
                    "message": "Opened a fix PR from the reviewed branch.",
                },
            },
            0,
            [],
            25,
        )

        self.assertIn("### Automatic Fix PR", body)
        self.assertIn("feature-agent-fixes-abcdef1", body)
        self.assertIn("https://github.com/example/repo/pull/2", body)
        self.assertIn("README diagram added: `true`", body)
        self.assertIn("Architecture documentation added: `true`", body)

    def test_review_body_includes_one_table_per_compliance_framework(self):
        body = build_review_body(
            {
                "summary": "summary",
                "outcome": "fail",
                "findings": [],
                "compliance_summary": {
                    "frameworks": [
                        {
                            "key": "gdpr",
                            "name": "GDPR",
                            "total_rules": 977,
                            "violations": 1,
                            "distinct_rule_count": 1,
                            "blocking": 1,
                            "warnings": 0,
                            "critical": 0,
                            "high": 1,
                            "medium": 0,
                            "low": 0,
                            "rule_ids": ["CHK-GDPR-Art32.1"],
                        },
                        {
                            "key": "soc2",
                            "name": "SOC 2",
                            "total_rules": 364,
                            "violations": 0,
                            "distinct_rule_count": 0,
                            "blocking": 0,
                            "warnings": 0,
                            "critical": 0,
                            "high": 0,
                            "medium": 0,
                            "low": 0,
                            "rule_ids": [],
                        },
                    ]
                },
            },
            0,
            [],
            25,
        )

        self.assertIn("### Compliance Framework Violation Counts", body)
        self.assertIn("#### GDPR", body)
        self.assertIn("#### SOC 2", body)
        self.assertIn("| Catalog rules loaded | `977` |", body)
        self.assertIn("`CHK-GDPR-Art32.1`", body)

    def test_passing_review_body_says_changes_resolved(self):
        result = normalize_review_result(
            {
                "summary": "clean",
                "outcome": "pass",
                "findings": [],
            }
        )
        body = build_review_body(
            result,
            0,
            [],
            25,
            {"requested_fingerprints": ["old-finding"]},
        )

        self.assertIn("### Changes Resolved", body)
        self.assertIn("| Changes resolved | `1` |", body)
        self.assertIn("| Tracked blockers | `1` |", body)
        self.assertNotIn("Requested blockers", body)
        self.assertEqual(marker_payload_from_body(body)["requested_fingerprints"], ["old-finding"])


if __name__ == "__main__":
    unittest.main()
