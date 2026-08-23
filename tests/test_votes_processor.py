import tempfile
import unittest
from pathlib import Path
import pandas as pd

from src.data_processing.votes_processor import VotesProcessor


class VotesProcessorTests(unittest.TestCase):
    def test_parse_vote_file_cleans_and_standardizes_columns(self):
        with tempfile.NamedTemporaryFile(suffix=".csv", mode="w", delete=False) as tmp:
            tmp.write(
                "Id,Ruolo,Nome,Squadra,Voto,Fantavoto,Gol,Assist,Amm,Esp\n"
                "101,A,Lautaro Martinez,Inter,7.5,10.5,1,0,0,0\n"
                "102,C,Nicolo Barella,Inter,6.5,7.5,0,1,1,0\n"
                "103,P,Yann Sommer,Inter,6.0,6.0,0,0,0,0\n"
            )
            tmp_path = Path(tmp.name)

        try:
            processor = VotesProcessor(season="2627")
            df = processor.parse_vote_file(tmp_path, matchday=1)

            self.assertEqual(len(df), 3)
            self.assertIn("player_normalized", df.columns)
            self.assertIn("vote", df.columns)
            self.assertIn("fantavoto", df.columns)
            self.assertEqual(df.loc[0, "player_normalized"], "lautaro martinez")
            self.assertEqual(df.loc[0, "vote"], 7.5)
            self.assertEqual(df.loc[0, "fantavoto"], 10.5)
            self.assertEqual(df.loc[0, "matchday"], 1)
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_parse_vote_file_handles_italian_comma_decimals(self):
        with tempfile.NamedTemporaryFile(suffix=".csv", mode="w", delete=False) as tmp:
            tmp.write(
                'Codice;Ruolo;Giocatore;Squadra;Voto;Fantavoto\n'
                '201;A;Rafael Leao;Milan;6,5;9,5\n'
            )
            tmp_path = Path(tmp.name)

        try:
            processor = VotesProcessor(season="2627")
            df = processor.parse_vote_file(tmp_path, matchday=5)
            self.assertEqual(len(df), 1)
            self.assertEqual(df.loc[0, "vote"], 6.5)
            self.assertEqual(df.loc[0, "fantavoto"], 9.5)
        finally:
            tmp_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
