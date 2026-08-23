"""Vote processing module for Fantacalcio weekly vote files."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

import pandas as pd

from config.settings import config
from src.utils.name_matching import normalize_name, normalize_team_name

logger = logging.getLogger(__name__)

# Standard column mapping from Italian Fantacalcio.it headers to normalized English names
VOTE_COLUMN_MAPPING = {
    "Id": "id",
    "ID": "id",
    "Codice": "id",
    "R": "role",
    "Ruolo": "role",
    "Nome": "player",
    "Giocatore": "player",
    "Squadra": "team",
    "Voto": "vote",
    "V": "vote",
    "Fantavoto": "fantavoto",
    "Fv": "fantavoto",
    "G": "goals",
    "Gol": "goals",
    "Gol Fatti": "goals",
    "Gf": "goals",
    "Gs": "goals_conceded",
    "Gol Subiti": "goals_conceded",
    "Rp": "penalties_saved",
    "Rigori Parati": "penalties_saved",
    "Rs": "penalties_missed",
    "Rigori Sbagliati": "penalties_missed",
    "Rf": "penalties_scored",
    "Aut": "own_goals",
    "Autogol": "own_goals",
    "Ass": "assists",
    "Assist": "assists",
    "Amm": "yellow_cards",
    "Ammonizioni": "yellow_cards",
    "Esp": "red_cards",
    "Espulsioni": "red_cards",
}


class VotesProcessor:
    """Processes weekly Fantacalcio votes from spreadsheet exports."""

    def __init__(self, season: Optional[str] = None) -> None:
        self.season = season or config.CURRENT_SEASON
        self.season_dir = config.get_season_dir(self.season)
        self.votes_dir = self.season_dir / "fantacalcio" / config.VOTES_DIR

    def parse_vote_file(self, filepath: Path, matchday: Optional[int] = None) -> pd.DataFrame:
        """Parse a single Fantacalcio vote file into a cleaned DataFrame."""
        filepath = Path(filepath)
        if not filepath.exists():
            raise FileNotFoundError(f"Vote file not found: {filepath}")

        if filepath.suffix in {".xlsx", ".xls"}:
            excel_data = pd.read_excel(filepath, sheet_name=None)
            # Use first sheet or sheet with matchday data
            sheet_name = list(excel_data.keys())[0]
            for key in excel_data:
                if "voti" in key.lower() or "tutti" in key.lower():
                    sheet_name = key
                    break
            df = excel_data[sheet_name]
        else:
            try:
                df = pd.read_csv(filepath, sep=None, engine="python")
            except Exception:
                df = pd.read_csv(filepath)

        # Detect and normalize header row if top rows are metadata
        if "Voto" not in df.columns and "voto" not in [str(c).lower() for c in df.columns]:
            for idx, row in df.head(10).iterrows():
                row_vals = [str(v).strip().lower() for v in row.values]
                if "voto" in row_vals or "ruolo" in row_vals or "nome" in row_vals:
                    df.columns = df.iloc[idx]
                    df = df.iloc[idx + 1:].reset_index(drop=True)
                    break

        # Standardize column names
        rename_map = {}
        for col in df.columns:
            cleaned = str(col).strip()
            if cleaned in VOTE_COLUMN_MAPPING:
                rename_map[col] = VOTE_COLUMN_MAPPING[cleaned]
            elif cleaned.capitalize() in VOTE_COLUMN_MAPPING:
                rename_map[col] = VOTE_COLUMN_MAPPING[cleaned.capitalize()]

        df = df.rename(columns=rename_map)

        # Infer matchday if not provided
        if matchday is None:
            match = re.search(r"(?:giornata|g|_|md)[_\s-]*(\d+)", filepath.stem, re.IGNORECASE)
            if match:
                matchday = int(match.group(1))

        if "matchday" not in df.columns and matchday is not None:
            df["matchday"] = matchday

        if "season" not in df.columns:
            df["season"] = self.season

        # Clean up data
        if "player" in df.columns:
            df["player"] = df["player"].astype(str).str.strip()
            df["player_normalized"] = df["player"].map(normalize_name)

        if "team" in df.columns:
            df["team"] = df["team"].astype(str).str.strip()
            df["team_normalized"] = df["team"].map(normalize_team_name)

        # Numeric conversions
        for num_col in ["vote", "fantavoto", "goals", "goals_conceded", "assists",
                        "yellow_cards", "red_cards", "penalties_saved", "penalties_missed"]:
            if num_col in df.columns:
                # Handle Italian decimal comma and non-voted players (marked as '*' or '-')
                df[num_col] = pd.to_numeric(
                    df[num_col].astype(str).str.replace(",", ".").str.replace("*", "", regex=False),
                    errors="coerce",
                ).fillna(0.0)

        # Filter out empty or header artifact rows
        if "player" in df.columns:
            df = df[df["player"].str.len() > 1].copy()

        return df

    def process_all_matchdays(self, max_matchday: Optional[int] = None) -> pd.DataFrame:
        """Process and concatenate all available weekly vote files in order."""
        if not self.votes_dir.exists():
            logger.warning(f"Votes directory does not exist: {self.votes_dir}")
            return pd.DataFrame()

        vote_files = sorted(list(self.votes_dir.glob("*.xlsx")) + list(self.votes_dir.glob("*.csv")))
        if not vote_files:
            logger.warning(f"No vote files found in {self.votes_dir}")
            return pd.DataFrame()

        frames = []
        for file in vote_files:
            match = re.search(r"(?:giornata|g|_|md)[_\s-]*(\d+)", file.stem, re.IGNORECASE)
            md = int(match.group(1)) if match else None
            if max_matchday is not None and md is not None and md > max_matchday:
                continue

            try:
                parsed = self.parse_vote_file(file, matchday=md)
                if not parsed.empty:
                    frames.append(parsed)
                    logger.info(f"Processed vote file: {file.name} ({len(parsed)} players)")
            except Exception as e:
                logger.error(f"Error parsing {file.name}: {e}")

        if not frames:
            return pd.DataFrame()

        combined = pd.concat(frames, ignore_index=True)
        return combined
