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

    @staticmethod
    def _clean_grade(raw_val: str, default: float = 6.0) -> float:
        """Parse raw grade string, normalizing comma decimals and scaling two-digit codes."""
        if not raw_val or str(raw_val).strip() in {"", "-", "*", "s.v.", "sv", "nan"}:
            return default
        cleaned = str(raw_val).replace(",", ".").replace("*", "").strip()
        try:
            val = float(cleaned)
            if val > 30.0:  # e.g. 55 -> 5.5, 60 -> 6.0, 135 -> 13.5
                val = val / 10.0
            return val
        except ValueError:
            return default

    @staticmethod
    def _matchday_from_filename(filepath: Path) -> Optional[int]:
        """Extract a matchday without treating aggregate archive files as rounds."""
        stem = filepath.stem.lower()
        if "full" in stem:
            return None
        match = re.search(r"(?:giornata|matchday|md)[_\s-]*(\d{1,2})", stem)
        return int(match.group(1)) if match else None

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
        for grade_col in ["vote", "fantavoto"]:
            if grade_col in df.columns:
                df[grade_col] = df[grade_col].map(lambda v: self._clean_grade(v, default=6.0))

        for num_col in ["goals", "goals_conceded", "assists",
                        "yellow_cards", "red_cards", "penalties_saved", "penalties_missed"]:
            if num_col in df.columns:
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

        vote_files = sorted(
            file for pattern in ("*.xlsx", "*.xls", "*.csv")
            for file in self.votes_dir.glob(pattern)
            if self._matchday_from_filename(file) is not None
        )
        if not vote_files:
            logger.warning(f"No vote files found in {self.votes_dir}")
            return pd.DataFrame()

        frames = []
        for file in vote_files:
            md = self._matchday_from_filename(file)
            if max_matchday is not None and md > max_matchday:
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
        natural_key = ["season", "matchday", "player_normalized", "team"]
        available_key = [column for column in natural_key if column in combined.columns]
        if available_key:
            combined = combined.drop_duplicates(available_key, keep="first")
        return combined.reset_index(drop=True)

    @classmethod
    def parse_matchday_html(cls, html_content: str, season: str = "2024-25", matchday: int = 1) -> pd.DataFrame:
        """Parse Fantacalcio.it matchday HTML table containing official votes and bonuses."""
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html_content, "lxml")
        records = []

        for table in soup.find_all("table"):
            header = table.find("tr")
            team_elem = header.find("th") if header else None
            team_name = team_elem.get_text(strip=True) if team_elem else ""

            for row in table.find_all("tr")[1:]:
                player_elem = row.find("a", class_="player-name")
                if not player_elem:
                    continue
                player_name = player_elem.get_text(strip=True)
                player_href = player_elem.get("href", "")
                player_id = re.search(r"/(\d+)/(?:\d{4}-\d{2})/?$", player_href)
                role_elem = row.find("span", class_="role")
                role = role_elem.get("data-value", "").upper() if role_elem else "C"

                grades = row.find_all("span", class_="player-grade")
                fanta_grades = row.find_all("span", class_="player-fanta-grade")

                # The public page exposes three pairs in this order:
                # editorial Fantacalcio, statistical, and Voto Italia.
                vote_values = [
                    cls._clean_grade(span.get("data-value", ""), default=6.0)
                    for span in grades[:3]
                ]
                fanta_values = [
                    cls._clean_grade(span.get("data-value", ""), default=6.0)
                    for span in fanta_grades[:3]
                ]
                while len(vote_values) < 3:
                    vote_values.append(6.0)
                while len(fanta_values) < 3:
                    fanta_values.append(vote_values[len(fanta_values)])

                vote = vote_values[0]
                fantavoto = fanta_values[0]

                bonuses: dict[str, float] = {}
                for b in row.find_all("span", class_="player-bonus"):
                    title = b.get("title", "").strip()
                    val = b.get("data-value", "0").replace(",", ".")
                    try:
                        bonuses[title] = float(val)
                    except ValueError:
                        bonuses[title] = 0.0

                records.append({
                    "season": season,
                    "matchday": matchday,
                    "team": team_name,
                    "player": player_name,
                    "id": player_id.group(1) if player_id else None,
                    "player_normalized": normalize_name(player_name),
                    "role": role,
                    "vote": vote,
                    "fantavoto": fantavoto,
                    "vote_fantacalcio": vote_values[0],
                    "fantavoto_fantacalcio": fanta_values[0],
                    "vote_statistical": vote_values[1],
                    "fantavoto_statistical": fanta_values[1],
                    "vote_italy": vote_values[2],
                    "fantavoto_italy": fanta_values[2],
                    "goals": bonuses.get("Gol segnati", 0.0),
                    "goals_conceded": bonuses.get("Gol subiti", 0.0),
                    "assists": bonuses.get("Assist", 0.0),
                    "yellow_cards": bonuses.get("Ammonizioni", 0.0),
                    "red_cards": bonuses.get("Espulsioni", 0.0),
                    "penalties_saved": bonuses.get("Rigori parati", 0.0),
                    "penalties_missed": bonuses.get("Rigori sbagliati", 0.0),
                    "penalties_scored": bonuses.get("Rigori segnati", 0.0),
                    "own_goals": bonuses.get("Autoreti", 0.0),
                })

        return pd.DataFrame(records)

    def fetch_online_matchday_votes(self, season_slug: str = "2024-25", matchday: int = 1) -> pd.DataFrame:
        """Fetch and parse official Fantacalcio.it votes for a given season and matchday."""
        import requests
        url = f"https://www.fantacalcio.it/voti-fantacalcio-serie-a/{season_slug}/{matchday}"
        headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7",
        }
        res = requests.get(url, headers=headers, timeout=20)
        res.raise_for_status()
        return self.parse_matchday_html(res.text, season=season_slug, matchday=matchday)
