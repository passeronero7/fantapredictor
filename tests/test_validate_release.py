import tempfile
import unittest
from pathlib import Path

from scripts.validate_release import validate_roster


class ReleaseValidationTests(unittest.TestCase):
    def test_validates_watchlist_and_confirmed_records(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "roster.csv"
            path.write_text(
                "player,club,role,status,source_url,checked_at\n"
                "Confirmed,Test FC,A,confirmed,https://example.test/1,2026-08-24\n"
                "Candidate,Test FC,,watchlist,https://example.test/2,2026-08-24\n",
                encoding="utf-8",
            )

            self.assertEqual(
                validate_roster(path, require_confirmed=True),
                {"confirmed": 1, "excluded": 0, "watchlist": 1},
            )

    def test_rejects_confirmed_pool_that_cannot_form_default_lineup(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "roster.csv"
            path.write_text(
                "player,club,role,status,source_url,checked_at\n"
                "Confirmed,Test FC,A,confirmed,https://example.test,2026-08-24\n",
                encoding="utf-8",
            )

            with self.assertRaises(ValueError):
                validate_roster(path, require_lineup=True)

    def test_requires_a_role_for_confirmed_records(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "roster.csv"
            path.write_text(
                "player,club,role,status,source_url,checked_at\n"
                "Confirmed,Test FC,,confirmed,https://example.test,2026-08-24\n",
                encoding="utf-8",
            )

            with self.assertRaises(ValueError):
                validate_roster(path)


if __name__ == "__main__":
    unittest.main()
