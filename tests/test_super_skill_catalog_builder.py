import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = REPO_ROOT / "tools"
sys.path.insert(0, str(TOOLS_DIR))

from build_super_skill_catalog import (  # noqa: E402
    build_catalog,
    classify_license,
    extract_source_entry,
    group_paths_by_repo,
    parse_github_url,
)


class SuperSkillCatalogBuilderTests(unittest.TestCase):
    def test_parses_github_repo_tree_and_blob_urls(self):
        tree = parse_github_url("https://github.com/example/tools/tree/main/skills/demo")
        self.assertEqual(tree["full_name"], "example/tools")
        self.assertEqual(tree["ref"], "main")
        self.assertEqual(tree["path"], "skills/demo")
        self.assertEqual(tree["kind"], "tree")

        blob = parse_github_url("https://github.com/example/tools/blob/main/commands/build.md")
        self.assertEqual(blob["kind"], "blob")
        self.assertEqual(blob["path"], "commands/build.md")

        repo = parse_github_url("https://github.com/example/tools")
        self.assertEqual(repo["kind"], "repo")
        self.assertEqual(repo["clone_url"], "https://github.com/example/tools.git")

    def test_groups_duplicate_repo_paths_by_repo_and_ref(self):
        grouped = group_paths_by_repo(
            [
                {"skill_name": "one", "category": "testing", "url": "https://github.com/acme/repo/tree/main/skills/one"},
                {"skill_name": "two", "category": "testing", "url": "https://github.com/acme/repo/tree/main/skills/two"},
                {"skill_name": "three", "category": "testing", "url": "https://github.com/acme/repo/tree/dev/skills/three"},
            ]
        )

        self.assertEqual(set(grouped), {("acme/repo", "main"), ("acme/repo", "dev")})
        self.assertEqual(grouped[("acme/repo", "main")], ["skills/one", "skills/two"])

    def test_classifies_compatible_and_unknown_licenses(self):
        self.assertEqual(
            classify_license("MIT License\n\nPermission is hereby granted, free of charge"),
            "mit",
        )
        self.assertEqual(classify_license("Custom internal terms only"), "unknown")

    def test_extracts_fixture_skill_with_commit_and_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "LICENSE").write_text(
                "MIT License\n\nPermission is hereby granted, free of charge",
                encoding="utf-8",
            )
            skill_dir = repo / "skills" / "demo"
            (skill_dir / "agents").mkdir(parents=True)
            (skill_dir / "scripts").mkdir()
            (skill_dir / "mcp").mkdir()
            (skill_dir / "SKILL.md").write_text(
                "---\nname: demo\ndescription: Use when testing generated catalog fixtures\n---\n\n# Demo\n\nReview Docker and GitHub Actions fixtures.",
                encoding="utf-8",
            )
            (skill_dir / "agents" / "openai.yaml").write_text("display_name: Demo\n", encoding="utf-8")
            (skill_dir / "scripts" / "fix.py").write_text("print('fixture')\n", encoding="utf-8")
            (skill_dir / "mcp" / "server.json").write_text(json.dumps({"name": "fixture"}), encoding="utf-8")

            subprocess.run(["git", "init"], cwd=repo, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            subprocess.run(["git", "add", "."], cwd=repo, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            subprocess.run(
                ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", "fixture"],
                cwd=repo,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            entry = extract_source_entry(
                {
                    "skill_name": "demo",
                    "category": "testing",
                    "url": "https://github.com/example/fixture/tree/main/skills/demo",
                },
                repo,
            )
            catalog = build_catalog([entry])

        self.assertEqual(entry["document_path"], "skills/demo/SKILL.md")
        self.assertRegex(entry["pinned_commit"], r"^[a-f0-9]{40}$")
        self.assertEqual(entry["license"], "mit")
        self.assertTrue(entry["license_compatible"])
        self.assertIn("agents/openai.yaml", entry["artifacts"]["agents"])
        self.assertIn("scripts/fix.py", entry["artifacts"]["scripts"])
        self.assertIn("mcp/server.json", entry["artifacts"]["mcp"])
        self.assertEqual(catalog["rule_count"], 19)
        self.assertEqual(catalog["rules"][0]["id"], "skill.testing.demo")


if __name__ == "__main__":
    unittest.main()
