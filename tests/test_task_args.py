"""Self-checks for splitting typed task arguments into argv.

    python3 -m unittest discover tests
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mise_shared import split_args  # noqa: E402


class SplitArgs(unittest.TestCase):
    def test_splits_on_whitespace(self):
        self.assertEqual(split_args(""), [])
        self.assertEqual(split_args("   "), [])
        self.assertEqual(split_args("bob --force"), ["bob", "--force"])

    def test_double_quotes_keep_a_run_together(self):
        self.assertEqual(split_args('a "b c"'), ["a", "b c"])
        self.assertEqual(split_args('--name="two words"'), ["--name=two words"])

    def test_single_quotes_and_backslashes_are_literal(self):
        """So apostrophes and Windows paths survive instead of erroring."""
        self.assertEqual(split_args("a 'b c'"), ["a", "'b", "c'"])
        self.assertEqual(split_args(r"C:\path\to\file"), [r"C:\path\to\file"])
        self.assertEqual(split_args("don't"), ["don't"])

    def test_unterminated_quote_raises(self):
        """MiseRunTaskCommand.run turns this into a status message."""
        for bad in ('a "unbalanced', '"'):
            with self.subTest(text=bad), self.assertRaises(ValueError):
                split_args(bad)


if __name__ == "__main__":
    unittest.main()
