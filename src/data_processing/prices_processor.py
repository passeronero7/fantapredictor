"""Public Fantacalcio quotation page parser."""

from __future__ import annotations

import re

import pandas as pd

from src.utils.name_matching import normalize_name


def parse_prices_html(html_content: str, season: str = "2026-27") -> pd.DataFrame:
    """Extract classic/mantra roles and current auction prices from public HTML."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html_content, "lxml")
    records = []
    for row in soup.select("tr.player-row"):
        player = row.select_one("a.player-name")
        if player is None:
            continue
        href = player.get("href", "")
        source_ref = next(iter(re.findall(r"/(\d+)(?:/|$)", href)), None)
        classic_role = row.select_one("th.player-role-classic span.role")
        mantra_role = row.select_one("th.player-role-mantra span.role")

        def cell(key: str) -> float | None:
            element = row.select_one(f"[data-col-key='{key}']")
            if element is None:
                return None
            try:
                return float(element.get_text(strip=True).replace(",", "."))
            except ValueError:
                return None

        records.append({
            "season": season,
            "player": player.get_text(" ", strip=True),
            "player_normalized": normalize_name(player.get_text(" ", strip=True)),
            "source_ref": source_ref,
            "team": (
                row.select_one("td.player-team").get_text(" ", strip=True)
                if row.select_one("td.player-team")
                else ""
            ),
            "role_classic": classic_role.get("data-value", "").upper() if classic_role else None,
            "role_mantra": mantra_role.get("data-value", "").lower() if mantra_role else None,
            "price_initial": cell("c_qi"),
            "price_current": cell("c_qa"),
            "fvm": cell("c_fvm"),
        })
    return pd.DataFrame(records)


def fetch_current_prices(season: str = "2026-27") -> pd.DataFrame:
    """Fetch the public quotation page for the requested season."""
    import requests

    url = "https://www.fantacalcio.it/quotazioni-fantacalcio"
    if season != "2026-27":
        url = f"https://www.fantacalcio.it/quotazioni-fantacalcio/{season}"
    response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    response.raise_for_status()
    return parse_prices_html(response.text, season=season)
