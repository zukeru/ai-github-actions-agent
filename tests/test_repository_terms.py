import os
import subprocess
import unittest


ROOT = os.path.dirname(os.path.dirname(__file__))
EXCLUDED_DIRS = {".git", "__pycache__"}
EXCLUDED_FILES = {"LICENSE", "test_repository_terms.py"}
FORBIDDEN_TERMS = [
    "DevOps",
    "devops-review",
    "Tillster",
    "TCE",
    "owner/devops-review",
    "platform-defaults",
    "standard CDK",
    "shared AWS",
    "approved construct",
]


class RepositoryTermsTests(unittest.TestCase):
    def test_old_project_specific_terms_are_removed(self):
        violations = []
        tracked_files = subprocess.run(
            ["git", "ls-files"],
            cwd=ROOT,
            check=True,
            stdout=subprocess.PIPE,
            text=True,
        ).stdout.splitlines()
        for rel in tracked_files:
            filename = os.path.basename(rel)
            if filename in EXCLUDED_FILES or any(part in EXCLUDED_DIRS for part in rel.split("/")):
                continue
            path = os.path.join(ROOT, rel)
            try:
                with open(path, "r", encoding="utf-8") as input_file:
                    text = input_file.read()
            except UnicodeDecodeError:
                continue
            for term in FORBIDDEN_TERMS:
                if term in text:
                    violations.append(f"{rel}: {term}")

        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
