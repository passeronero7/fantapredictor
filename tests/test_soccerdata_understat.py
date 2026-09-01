import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from src.data_processing.soccerdata_understat import (
    ARCHIVE_COLUMNS,
    compact_season,
    download_player_season_stats,
    season_start_year,
    to_understat_archive,
)


def sample_stats() -> pd.DataFrame:
    return pd.DataFrame(
        [{
            "league": "ITA-Serie A", "season": "2526", "team": "Test FC", "player": "Test Player",
            "league_id": 2, "season_id": 2025, "team_id": 99, "player_id": 7, "position": "F",
            "matches": 20, "minutes": 1600, "goals": 9, "xg": 8.5, "np_goals": 8, "np_xg": 7.9,
            "assists": 4, "xa": 3.2, "shots": 45, "key_passes": 30, "yellow_cards": 2,
            "red_cards": 0, "xg_chain": 12.1, "xg_buildup": 4.3,
        }]
    ).set_index(["league", "season", "team", "player"])


class SeasonParsingTests(unittest.TestCase):
    def test_accepts_compact_year_and_human_season_inputs(self):
        self.assertEqual(season_start_year("2627"), 2026)
        self.assertEqual(season_start_year("2026"), 2026)
        self.assertEqual(season_start_year("2026-27"), 2026)
        self.assertEqual(compact_season("2026/27"), "2627")

    def test_rejects_invalid_season_range(self):
        with self.assertRaises(ValueError):
            season_start_year("2026-29")

    def test_disambiguates_compact_codes_starting_with_19_or_20(self):
        # "1920" and "2021" are compact YYZZ codes, not literal years: they
        # must resolve the same way as src.db.ingestors.common.season_label.
        self.assertEqual(season_start_year("1920"), 2019)
        self.assertEqual(season_start_year("2021"), 2020)


class SoccerdataUnderstatTests(unittest.TestCase):
    def test_adapter_matches_existing_understat_ingestor_contract(self):
        archive = to_understat_archive(sample_stats(), 2025)

        self.assertEqual(archive.columns.tolist(), ARCHIVE_COLUMNS)
        self.assertEqual(archive.loc[0, "player_name"], "Test Player")
        self.assertEqual(archive.loc[0, "league"], "Serie_A")
        self.assertEqual(archive.loc[0, "npxG"], 7.9)

    def test_download_writes_csv_and_provenance_manifest_without_network(self):
        calls = []

        class FakeReader:
            def read_player_season_stats(self):
                return sample_stats()

        def factory(**kwargs):
            calls.append(kwargs)
            return FakeReader()

        with tempfile.TemporaryDirectory() as temporary:
            report = download_player_season_stats("2526", temporary, reader_factory=factory)
            csv_path = Path(report["data_path"])
            manifest = json.loads(Path(report["manifest_path"]).read_text(encoding="utf-8"))

            self.assertEqual(calls[0]["leagues"], "ITA-Serie A")
            self.assertEqual(calls[0]["seasons"], 2025)
            self.assertTrue(str(calls[0]["data_dir"]).endswith("cache"))
            self.assertTrue(csv_path.exists())
            self.assertEqual(pd.read_csv(csv_path).columns.tolist(), ARCHIVE_COLUMNS)
            self.assertEqual(manifest["rows"], 1)
            self.assertEqual(manifest["source_url"], "https://understat.com/league/Serie_A/2025")

            with self.assertRaises(FileExistsError):
                download_player_season_stats("2526", temporary, reader_factory=factory)


if __name__ == "__main__":
    unittest.main()
