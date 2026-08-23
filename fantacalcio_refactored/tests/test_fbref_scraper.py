import unittest

from bs4 import BeautifulSoup
import pandas as pd

from src.scrapers.fbref_scraper import FBRefScraper


class FBRefTableParsingTests(unittest.TestCase):
    def setUp(self):
        # Avoid the live-session dependency; these tests cover parsing only.
        self.scraper = FBRefScraper.__new__(FBRefScraper)

    def test_player_parser_keeps_missing_cells_aligned(self):
        table = BeautifulSoup(
            '''<tbody><tr><th scope="row">1</th>
            <td data-stat="player">Test Player</td>
            <td data-stat="squad">Test Club</td>
            <td data-stat="goals">3</td></tr>
            <tr><th scope="row">2</th>
            <td data-stat="player">Second Player</td>
            <td data-stat="squad">Second Club</td></tr></tbody>''',
            "lxml",
        ).tbody

        result = self.scraper._parse_player_table(table, ["player", "team", "goals"])

        self.assertEqual(result.shape, (2, 3))
        self.assertEqual(result.loc[0, "team"], "Test Club")
        self.assertEqual(result.loc[0, "goals"], 3.0)
        self.assertTrue(pd.isna(result.loc[1, "goals"]))

    def test_team_parser_keeps_missing_cells_aligned(self):
        table = BeautifulSoup(
            '''<tbody><tr><th scope="row" data-stat="team">Test Club</th>
            <td data-stat="goals">12</td></tr></tbody>''', "lxml"
        ).tbody

        result = self.scraper._parse_team_table(table, ["goals", "assists"])

        self.assertEqual(result.shape, (1, 3))
        self.assertEqual(result.loc[0, "team"], "Test Club")
        self.assertEqual(result.loc[0, "goals"], 12.0)
        self.assertTrue(pd.isna(result.loc[0, "assists"]))


if __name__ == "__main__":
    unittest.main()
