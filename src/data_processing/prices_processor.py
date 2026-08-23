"""Public Fantacalcio quotation page parser."""

from __future__ import annotations

import re

import pandas as pd

from src.utils.name_matching import normalize_name


def _surname_initial(name: str) -> tuple[str, str]:
    """Return a surname/initial pair for full and ``Surname I.`` names."""
    tokens = normalize_name(name).split()
    if not tokens:
        return "", ""
    if len(tokens) > 1 and len(tokens[-1]) == 1:
        return tokens[0], tokens[-1]
    return tokens[-1], tokens[0][0]


def merge_current_prices(players_df: pd.DataFrame, prices_df: pd.DataFrame) -> pd.DataFrame:
    """Attach quotation roles and prices using conservative identity matching."""
    output = players_df.copy()
    if output.empty or prices_df.empty or "player" not in output.columns:
        return output
    if "player_normalized" not in output.columns:
        output["player_normalized"] = output["player"].map(normalize_name)

    canonical_names = output["player"].astype(str).map(normalize_name)
    exact = {}
    signatures = {}
    for index, name in canonical_names.items():
        exact.setdefault(name, []).append(index)
        signatures.setdefault(_surname_initial(name), []).append(index)

    for column in ("price", "price_current", "fvm", "role_classic", "role_mantra"):
        if column not in output.columns:
            output[column] = pd.NA
    output["price_match"] = "unmatched"

    for _, price_row in prices_df.iterrows():
        price_name = str(price_row.get("player", ""))
        normalized = normalize_name(price_name)
        candidates = exact.get(normalized, [])
        match_type = "exact"
        if len(candidates) != 1:
            candidates = signatures.get(_surname_initial(price_name), [])
            match_type = "surname_initial"
        if len(candidates) != 1:
            continue
        index = candidates[0]
        current_price = price_row.get("price_current")
        output.at[index, "price"] = current_price
        output.at[index, "price_current"] = current_price
        output.at[index, "fvm"] = price_row.get("fvm")
        output.at[index, "role_classic"] = price_row.get("role_classic")
        output.at[index, "role_mantra"] = price_row.get("role_mantra")
        if pd.notna(price_row.get("role_classic")):
            output.at[index, "role"] = price_row.get("role_classic")
        output.at[index, "price_match"] = match_type
    return output


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
