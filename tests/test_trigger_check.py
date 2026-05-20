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

from review_common import body_has_trigger, parse_trigger_phrases  # noqa: E402


class TriggerTests(unittest.TestCase):
    def test_accepts_primary_trigger(self):
        phrases = parse_trigger_phrases("@gha-agent-review,@gha-agent-revew")
        self.assertTrue(body_has_trigger("please run @gha-agent-review", phrases))

    def test_accepts_typo_alias(self):
        phrases = parse_trigger_phrases("@gha-agent-review,@gha-agent-revew")
        self.assertTrue(body_has_trigger("@gha-agent-revew this", phrases))

    def test_ignores_unrelated_comment(self):
        phrases = parse_trigger_phrases("@gha-agent-review,@gha-agent-revew")
        self.assertFalse(body_has_trigger("looks good", phrases))


if __name__ == "__main__":
    unittest.main()

