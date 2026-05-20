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

from compliance_rules import (  # noqa: E402
    apply_compliance_mapping,
    build_compliance_prompt_context,
    load_compliance_catalog,
)


class ComplianceRulesTests(unittest.TestCase):
    def test_catalog_loads_all_frameworks(self):
        catalog = load_compliance_catalog()
        keys = {framework["key"] for framework in catalog["frameworks"]}

        self.assertEqual(
            keys,
            {
                "gdpr",
                "hipaa",
                "hitrust",
                "iso27001",
                "nist_ai_rmf",
                "nist_sp80053r5",
                "pci_dss_v4_0_1",
                "soc2",
            },
        )
        self.assertGreater(sum(len(item["rules"]) for item in catalog["frameworks"]), 6000)

    def test_prompt_context_includes_matching_rules(self):
        catalog = load_compliance_catalog()
        context = {
            "files": [{"filename": "infra/network.tf"}],
            "file_contents": {
                "infra/network.tf": "resource allows public ssh ingress from 0.0.0.0/0 and weak network segmentation"
            },
        }

        prompt_context = build_compliance_prompt_context(catalog, context)

        self.assertEqual(len(prompt_context["frameworks"]), 8)
        self.assertTrue(
            any(framework["matching_rules"] for framework in prompt_context["frameworks"])
        )

    def test_maps_findings_to_framework_counts(self):
        catalog = load_compliance_catalog()
        result = {
            "findings": [
                {
                    "path": "infra/network.tf",
                    "line": 12,
                    "severity": "high",
                    "blocks_merge": True,
                    "rule_id": "iac.network.public-management",
                    "title": "Restrict public management access",
                    "body": "Public SSH ingress from 0.0.0.0/0 exposes management access and weakens network segmentation.",
                }
            ]
        }

        mapped = apply_compliance_mapping(result, catalog)
        frameworks = mapped["compliance_summary"]["frameworks"]

        self.assertEqual(len(frameworks), 8)
        self.assertTrue(any(item["violations"] > 0 for item in frameworks))
        self.assertTrue(mapped["findings"][0]["compliance_frameworks"])
        self.assertTrue(mapped["findings"][0]["compliance_rule_ids"])


if __name__ == "__main__":
    unittest.main()
