import unittest

import pandas as pd

from scripts.simulate_auction_propensity import NON_TITOLAR_FACTOR, formation_factors


class FormationFactorTests(unittest.TestCase):
    def setUp(self):
        self.formations = pd.DataFrame([
            {"club": "Juventus", "titulars": "Thuram K.;Vlahovic", "source_refs": "101;102"},
            {"club": "Inter", "titulars": "Lautaro;Barella", "source_refs": "201;202"},
        ])
        self.prices = pd.DataFrame([
            {"player_normalized": "thuram k", "source_ref": 101},
            {"player_normalized": "thuram", "source_ref": 203},
            {"player_normalized": "barella", "source_ref": 202},
        ])

    def factors(self, rows):
        return list(formation_factors(pd.DataFrame(rows), self.formations, self.prices))

    def test_titolar_is_identified_by_official_id(self):
        rows = [{"player": "Barella", "player_normalized": "barella", "team": "Inter"}]
        self.assertEqual(self.factors(rows), [1.0])

    def test_name_substring_from_another_club_does_not_count(self):
        # Marcus Thuram (Inter, not in the probable XI) must not inherit
        # Khephren Thuram's Juventus titolar status through "thuram" ⊂ "thuram k".
        rows = [{"player": "Thuram", "player_normalized": "thuram", "team": "Inter"}]
        self.assertEqual(self.factors(rows), [NON_TITOLAR_FACTOR])

    def test_name_fallback_is_exact_and_club_scoped(self):
        rows = [
            {"player": "Vlahovic", "player_normalized": "vlahovic", "team": "Juventus"},
            {"player": "Vlahovic", "player_normalized": "vlahovic", "team": "Inter"},
        ]
        self.assertEqual(self.factors(rows), [1.0, NON_TITOLAR_FACTOR])


if __name__ == "__main__":
    unittest.main()
