import unittest

import pandas as pd

from scripts.reconcile_official_transfers import normalize_transfers, reconcile_roster


class OfficialTransferReconciliationTests(unittest.TestCase):
    def test_normalize_transfers_keeps_latest_official_incoming_move(self):
        items = [
            {"selfUrl": "https://official.test/old", "fields": {
                "playerName": "Andrea", "playerSurname": "Player", "clubTo3Code": "TOR",
                "role": "Centrocampista", "transferDate": "2026-08-01T10:00:00Z",
            }},
            {"selfUrl": "https://official.test/new", "fields": {
                "playerName": "Andrea", "playerSurname": "Player", "clubTo3Code": "LEC",
                "role": "Centrocampista", "transferDate": "2026-08-02T10:00:00Z",
            }},
        ]
        transfers = normalize_transfers(items)
        self.assertEqual(len(transfers), 1)
        self.assertEqual(transfers.loc[0, "club"], "Lecce")
        self.assertEqual(transfers.loc[0, "role"], "C")

    def test_reconcile_marks_previous_club_excluded_and_missing_roles_watchlist(self):
        roster = pd.DataFrame([
            {"player": "Andrea Player", "club": "Torino", "club_2026_27": "Torino", "role": "C", "status": "confirmed", "source_url": "old", "checked_at": "old"},
        ])
        transfers = pd.DataFrame([
            {"player": "Andrea Player", "player_normalized": "andrea player", "club": "Lecce", "role": "", "source_url": "official"},
        ])
        result, counts = reconcile_roster(roster, transfers, "2026-08-28T00:00:00+00:00")
        self.assertEqual(counts["created"], 1)
        self.assertEqual(result.loc[result["club"] == "Torino", "status"].iloc[0], "excluded")
        self.assertEqual(result.loc[result["club"] == "Lecce", "status"].iloc[0], "watchlist")
