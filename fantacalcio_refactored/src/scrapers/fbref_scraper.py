"""
FBRef web scraper for Serie A player and team statistics.

Original code by parth1902: https://github.com/parth1902/Scrape-FBref-data
Adapted for Fantacalcio project.
Hardened version (2026) with session, headers and rate limiting protection.
"""

#import requests
import cloudscraper
from bs4 import BeautifulSoup
import pandas as pd
import re
import logging
import time
from typing import Optional
from pathlib import Path

from config.settings import config

logger = logging.getLogger(__name__)


class FBRefScraper:
    """Scraper for FBRef.com Serie A statistics."""

    def __init__(self, base_url: str = None, suffix: str = None,
                 season: str = None):
        self.base_url = base_url or config.get_fbref_base_url(season)
        self.suffix = suffix or config.FBREF_SERIE_A_SUFFIX

        # Use persistent session (important for cookies + anti-bot mitigation)
        #self.session = requests.Session()
        #self.session.headers.update({
        #    "User-Agent": (
        #        "Mozilla/5.0 (X11; Linux x86_64) "
        #        "AppleWebKit/537.36 (KHTML, like Gecko) "
        #        "Chrome/120.0.0.0 Safari/537.36"
        #    ),
        #    "Accept-Language": "en-US,en;q=0.9",
        #    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        #    "Referer": "https://fbref.com/",
        #    "Connection": "keep-alive",
        #}
        self.session = cloudscraper.create_scraper(
            browser={
                "browser": "chrome",
                "platform": "linux",
                "mobile": False,
            }
        )

    def _get_tables(self, url: str, table_type: str = 'for'):
        try:
            # Small delay to avoid rate limiting
            time.sleep(2)

            res = self.session.get(url, timeout=30)
            res.raise_for_status()

            # Remove HTML comments (FBRef wraps tables in comments)
            comm = re.compile("<!--|-->")
            soup = BeautifulSoup(comm.sub("", res.text), 'lxml')
            all_tables = soup.find_all("tbody")

            if len(all_tables) < 3:
                logger.warning(f"Expected at least 3 tables, found {len(all_tables)}")
                return None, None

            team_table = all_tables[0] if table_type == 'for' else all_tables[1]
            player_table = all_tables[2]

            return player_table, team_table

        #except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP error fetching {url}: {e}")
            raise
        except Exception as e:
            logger.error(f"Error fetching tables from {url}: {e}")
            raise

    @staticmethod
    def _cell_value(row, feature: str):
        """Return one FBref cell value, preserving a rectangular table shape."""
        stat_name = 'squad' if feature == 'team' else feature
        cell = row.find("td", {"data-stat": stat_name})
        if cell is None:
            return None

        text = cell.text.strip()
        if feature in {'player', 'nationality', 'position', 'squad', 'age',
                       'birth_year', 'team'}:
            return text or None
        if not text:
            return 0.0
        try:
            return float(text.replace(',', ''))
        except ValueError:
            logger.warning("Non-numeric FBref value for %s: %r", feature, text)
            return None

    def _parse_player_table(self, table, features: list) -> pd.DataFrame:
        records = []
        for row in table.find_all('tr'):
            if row.find('th', {"scope": "row"}) is None:
                continue
            records.append({feature: self._cell_value(row, feature)
                            for feature in features})
        return pd.DataFrame.from_records(records, columns=features)

    def _parse_team_table(self, table, features: list,
                          team_col: str = 'team') -> pd.DataFrame:
        records = []
        for row in table.find_all('tr'):
            if row.find('th', {"scope": "row"}) is None:
                continue
            name_cell = row.find('th', {"data-stat": team_col})
            record = {team_col: name_cell.text.strip() if name_cell else None}
            record.update({feature: self._cell_value(row, feature)
                           for feature in features})
            records.append(record)

        return pd.DataFrame.from_records(records, columns=[team_col, *features])

    def _get_category_data(self, category: str, features: list) -> pd.DataFrame:
        url = self.base_url + category + self.suffix
        logger.info(f"Scraping {category} from {url}")

        player_table, _ = self._get_tables(url, 'for')
        if player_table is None:
            return pd.DataFrame()

        return self._parse_player_table(player_table, features)

    def _get_team_category_data(self, category: str, features: list,
                                table_type: str = 'for') -> pd.DataFrame:
        url = self.base_url + category + self.suffix
        logger.info(f"Scraping team {category} ({table_type}) from {url}")

        _, team_table = self._get_tables(url, table_type)
        if team_table is None:
            return pd.DataFrame()

        team_col = 'team' if table_type == 'for' else 'squad'
        return self._parse_team_table(team_table, features, team_col)

    def scrape_outfield_players(self) -> pd.DataFrame:
        logger.info("Starting outfield players scrape...")

        df1 = self._get_category_data('stats', config.OUTFIELD_STATS)

        shooting_features = [f for f in config.SHOOTING_STATS
                             if f not in ['player', 'nationality', 'position',
                                          'team', 'age', 'birth_year']]
        df2 = self._get_category_data('shooting', shooting_features)

        passing_features = [f for f in config.PASSING_STATS
                            if f not in ['player', 'nationality', 'position',
                                         'team', 'age', 'birth_year']]
        df3 = self._get_category_data('passing', passing_features)

        pass_types_features = [f for f in config.PASS_TYPES_STATS
                               if f not in ['player', 'nationality', 'position',
                                            'team', 'age', 'birth_year']]
        df4 = self._get_category_data('passing_types', pass_types_features)

        gca_features = [f for f in config.GCA_STATS
                        if f not in ['player', 'nationality', 'position',
                                     'team', 'age', 'birth_year']]
        df5 = self._get_category_data('gca', gca_features)

        defense_features = [f for f in config.DEFENSE_STATS
                            if f not in ['player', 'nationality', 'position',
                                         'team', 'age', 'birth_year']]
        df6 = self._get_category_data('defense', defense_features)

        possession_features = [f for f in config.POSSESSION_STATS
                               if f not in ['player', 'nationality', 'position',
                                            'team', 'age', 'birth_year']]
        df7 = self._get_category_data('possession', possession_features)

        misc_features = [f for f in config.MISC_STATS
                         if f not in ['player', 'nationality', 'position',
                                      'team', 'age', 'birth_year']]
        df8 = self._get_category_data('misc', misc_features)

        df = pd.concat([df1, df2, df3, df4, df5, df6, df7, df8], axis=1)
        df = df.loc[:, ~df.columns.duplicated()]

        logger.info(f"Scraped {len(df)} outfield players with {len(df.columns)} features")
        return df

    def scrape_goalkeepers(self) -> pd.DataFrame:
        logger.info("Starting goalkeepers scrape...")

        df1 = self._get_category_data('keepers', config.GK_STATS)

        gk_adv_features = [f for f in config.GK_ADV_STATS
                           if f not in ['player', 'nationality', 'position',
                                        'team', 'age', 'birth_year']]
        df2 = self._get_category_data('keepersadv', gk_adv_features)

        df = pd.concat([df1, df2], axis=1)
        df = df.loc[:, ~df.columns.duplicated()]

        logger.info(f"Scraped {len(df)} goalkeepers with {len(df.columns)} features")
        return df

    def scrape_team_stats(self, for_against: str = 'for') -> pd.DataFrame:
        logger.info(f"Starting team stats scrape ({for_against})...")

        categories = {
            'stats': config.OUTFIELD_STATS[6:],
            'keepers': config.GK_STATS[6:],
            'keepersadv': config.GK_ADV_STATS[6:],
            'shooting': config.SHOOTING_STATS[6:],
            'passing': config.PASSING_STATS[6:],
            'passing_types': config.PASS_TYPES_STATS[6:],
            'gca': config.GCA_STATS[6:],
            'defense': config.DEFENSE_STATS[6:],
            'possession': config.POSSESSION_STATS[6:],
            'misc': config.MISC_STATS[6:],
        }

        dfs = []
        for category, features in categories.items():
            df_cat = self._get_team_category_data(category, features, for_against)
            if not df_cat.empty:
                dfs.append(df_cat)

        if not dfs:
            return pd.DataFrame()

        df = pd.concat(dfs, axis=1)
        df = df.loc[:, ~df.columns.duplicated()]

        logger.info(f"Scraped {len(df)} teams with {len(df.columns)} features")
        return df

    def scrape_all(self, save_dir: Optional[Path] = None,
                   season: Optional[str] = None) -> dict:

        results = {}

        results['outfield'] = self.scrape_outfield_players()
        results['goalkeepers'] = self.scrape_goalkeepers()
        results['teams_for'] = self.scrape_team_stats('for')
        results['teams_vs'] = self.scrape_team_stats('vs')

        if save_dir:
            save_dir = Path(save_dir)
            if season:
                save_dir = save_dir / f'season{season}'
            save_dir.mkdir(parents=True, exist_ok=True)

            results['outfield'].to_csv(save_dir / config.OUTFIELD_PLAYERS_FILE, index=False)
            results['goalkeepers'].to_csv(save_dir / config.KEEPERS_FILE, index=False)
            results['teams_for'].to_csv(save_dir / config.TEAMS_FILE, index=False)
            results['teams_vs'].to_csv(save_dir / config.TEAMS_VS_FILE, index=False)

            logger.info(f"Saved all scraped data to {save_dir}")

        return results
