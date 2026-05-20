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

from review_common import changed_line_sources_from_patch, changed_lines_from_patch  # noqa: E402


class DiffMappingTests(unittest.TestCase):
    def test_maps_added_lines_only(self):
        patch = """@@ -1,3 +1,4 @@
 line one
-old line
+new line
 line three
+new line four
"""
        self.assertEqual(changed_lines_from_patch(patch), {2, 4})

    def test_maps_added_line_source_text(self):
        patch = """@@ -1,3 +1,4 @@
 line one
-old line
+new line
 line three
+new line four
"""
        self.assertEqual(
            changed_line_sources_from_patch(patch),
            {2: "new line", 4: "new line four"},
        )

    def test_handles_empty_patch(self):
        self.assertEqual(changed_lines_from_patch(""), set())

    def test_handles_multiple_hunks(self):
        patch = """@@ -1,2 +1,2 @@
-a
+b
 c
@@ -10,2 +10,3 @@
 x
+y
 z
"""
        self.assertEqual(changed_lines_from_patch(patch), {1, 11})


if __name__ == "__main__":
    unittest.main()
