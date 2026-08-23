import unittest

import pandas as pd

from src.data_processing.prices_processor import merge_current_prices, parse_prices_html


class PricesProcessorTests(unittest.TestCase):
    def test_parse_prices_html_extracts_roles_prices_and_fvm(self):
        html = """
        <table><tr class="player-row">
          <th class="player-role player-role-classic"><span class="role" data-value="d"></span></th>
          <th class="player-role player-role-mantra"><span class="role" data-value="dd"></span></th>
          <th class="player-name"><a class="player-name" href="/serie-a/x/player/123/2026-27">Test Defender</a></th>
          <td class="player-team" data-col-key="sq">INT</td>
          <td data-col-key="c_qi">10</td><td data-col-key="c_qa">12</td><td data-col-key="c_fvm">80</td>
          <td data-col-key="m_qi">10</td><td data-col-key="m_qa">12</td><td data-col-key="m_fvm">80</td>
        </tr></table>
        """
        frame = parse_prices_html(html)
        self.assertEqual(len(frame), 1)
        row = frame.iloc[0]
        self.assertEqual(row["source_ref"], "123")
        self.assertEqual(row["role_classic"], "D")
        self.assertEqual(row["price_current"], 12.0)
        self.assertEqual(row["fvm"], 80.0)

    def test_merge_matches_abbreviated_quotation_names(self):
        players = pd.DataFrame([{
            "player": "Lautaro Martinez",
            "player_normalized": "lautaro martinez",
            "role": "F",
        }])
        prices = pd.DataFrame([{
            "player": "Martinez L.",
            "price_current": 35,
            "fvm": 370,
            "role_classic": "A",
            "role_mantra": "pc",
        }])

        result = merge_current_prices(players, prices)

        self.assertEqual(result.loc[0, "price"], 35)
        self.assertEqual(result.loc[0, "role"], "A")
        self.assertEqual(result.loc[0, "price_match"], "surname_initial")


if __name__ == "__main__":
    unittest.main()
