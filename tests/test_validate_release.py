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
                "Confirmed,Inter,A,confirmed,https://example.test/1,2026-08-24\n"
                "Candidate,Inter,,watchlist,https://example.test/2,2026-08-24\n",
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
                "Confirmed,Inter,A,confirmed,https://example.test,2026-08-24\n",
                encoding="utf-8",
            )

            with self.assertRaises(ValueError):
                validate_roster(path, require_lineup=True)

    def test_requires_a_role_for_confirmed_records(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "roster.csv"
            path.write_text(
                "player,club,role,status,source_url,checked_at\n"
                "Confirmed,Inter,,confirmed,https://example.test,2026-08-24\n",
                encoding="utf-8",
            )

            with self.assertRaises(ValueError):
                validate_roster(path)

    def test_priced_gate_passes_when_every_slot_has_a_priced_player(self):
        with tempfile.TemporaryDirectory() as temporary:
            roster_path = Path(temporary) / "roster.csv"
            roster_path.write_text(
                "player,club,role,status,source_url,checked_at\n"
                " Keeper,Inter,P,confirmed,https://example.test,2026-08-24\n"
                " Back One,Inter,D,confirmed,https://example.test,2026-08-24\n"
                " Back Two,Inter,D,confirmed,https://example.test,2026-08-24\n"
                " Back Three,Inter,D,confirmed,https://example.test,2026-08-24\n"
                " Mid One,Inter,C,confirmed,https://example.test,2026-08-24\n"
                " Mid Two,Inter,C,confirmed,https://example.test,2026-08-24\n"
                " Mid Three,Inter,C,confirmed,https://example.test,2026-08-24\n"
                " Mid Four,Inter,C,confirmed,https://example.test,2026-08-24\n"
                " Striker One,Inter,A,confirmed,https://example.test,2026-08-24\n"
                " Striker Two,Inter,A,confirmed,https://example.test,2026-08-24\n"
                " Striker Three,Inter,A,confirmed,https://example.test,2026-08-24\n"
                " Unpriced,Inter,A,confirmed,https://example.test,2026-08-24\n",
                encoding="utf-8",
            )
            prices_path = Path(temporary) / "prices.csv"
            prices_path.write_text(
                "season,player,player_normalized,source_ref,team,role_classic,role_mantra,price_initial,price_current,fvm\n"
                + "".join(
                    f"2026-27,{name},test,X,INT,{role},pc,1.0,1.0,1.0\n"
                    for name, role in [
                        ("Keeper", "P"), ("Back One", "D"), ("Back Two", "D"), ("Back Three", "D"),
                        ("Mid One", "C"), ("Mid Two", "C"), ("Mid Three", "C"), ("Mid Four", "C"),
                        ("Striker One", "A"), ("Striker Two", "A"), ("Striker Three", "A"),
                    ]
                ),
                encoding="utf-8",
            )
            counts = validate_roster(
                roster_path, require_priced=True, prices_path=prices_path,
            )
            self.assertEqual(counts["priced_confirmed"], 11)

    def test_priced_gate_fails_without_a_priced_goalkeeper(self):
        with tempfile.TemporaryDirectory() as temporary:
            roster_path = Path(temporary) / "roster.csv"
            roster_path.write_text(
                "player,club,role,status,source_url,checked_at\n"
                " Keeper,Inter,P,confirmed,https://example.test,2026-08-24\n"
                " Back One,Inter,D,confirmed,https://example.test,2026-08-24\n",
                encoding="utf-8",
            )
            prices_path = Path(temporary) / "prices.csv"
            prices_path.write_text(
                "season,player,player_normalized,source_ref,team,role_classic,role_mantra,price_initial,price_current,fvm\n"
                "2026-27,Back One,back one,X,INT,D,pc,1.0,1.0,1.0\n",
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                validate_roster(roster_path, require_priced=True, prices_path=prices_path)


if __name__ == "__main__":
    unittest.main()
