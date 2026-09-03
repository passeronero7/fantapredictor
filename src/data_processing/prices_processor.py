"""Public Fantacalcio quotation page parser."""

from __future__ import annotations

import re

import pandas as pd

from src.utils.name_matching import normalize_name


def _surname_initial(name: str) -> tuple[str, str]:
    """Return a surname/initial pair for full and ``Surname I.`` names.

    The surname is everything but the first name token (assumed single-word)
    on the full-name side, and everything but the trailing initial on the
    abbreviated ``Surname I.`` side, so multi-word surnames (``De Bruyne``,
    ``El Shaarawy``) still produce matching signatures on both sides instead
    of only comparing their first word.
    """
    tokens = normalize_name(name).split()
    if not tokens:
        return "", ""
    if len(tokens) == 1:
        return tokens[0], tokens[0][0]
    if len(tokens[-1]) == 1:
        return " ".join(tokens[:-1]), tokens[-1]
    return " ".join(tokens[1:]), tokens[0][0]


def _surname_tokens(name: str) -> tuple[str, str]:
    """Return ``(surname, first_name_initial)`` from a normalized full name.

    Unlike :func:`_surname_initial`, the surname is always the trailing run of
    tokens, so a quotation that lists only the surname (``Dimarco``) matches a
    roster full name (``Federico Dimarco``) even when the quotation cannot
    carry a first-name initial.
    """
    tokens = normalize_name(name).split()
    if not tokens:
        return "", ""
    if len(tokens) == 1:
        return tokens[0], ""
    if len(tokens[-1]) == 1:
        return " ".join(tokens[:-1]), tokens[-1]
    return " ".join(tokens[1:]), tokens[0][0]


def _surname_tail(name: str) -> str:
    """Return the distinctive last token of a name's surname.

    Trailing one/two-letter tokens are initials (``Sanchez Ro.``,
    ``Esposito F.P.``) and are dropped, so ``Di Lorenzo``, ``Giovanni Di
    Lorenzo`` and ``De Bruyne``/``Kevin De Bruyne`` all reduce to their final
    surname token. Particle prefixes (``de``, ``di``, ``da``...) survive in
    the middle but never drive the comparison.
    """
    tokens = [token for token in normalize_name(name).split() if token]
    while len(tokens) > 1 and len(tokens[-1]) <= 2:
        tokens.pop()
    return tokens[-1] if tokens else ""


# Fantacalcio quotation 3-letter club codes mapped to canonical warehouse clubs.
FANTACALCIO_TEAM_CODES = {
    "ATA": "Atalanta", "BOL": "Bologna", "CAG": "Cagliari", "COM": "Como",
    "FIO": "Fiorentina", "FRO": "Frosinone", "GEN": "Genoa", "INT": "Inter",
    "JUV": "Juventus", "LAZ": "Lazio", "LEC": "Lecce", "MIL": "Milan",
    "MON": "Monza", "NAP": "Napoli", "PAR": "Parma", "ROM": "Roma",
    "SAS": "Sassuolo", "TOR": "Torino", "UDI": "Udinese", "VEN": "Venezia",
}


def match_prices_to_roster(
    roster: pd.DataFrame,
    prices: pd.DataFrame,
    club_column: str = "club_2026_27",
) -> pd.DataFrame:
    """Match quotation rows to roster rows within the same club.

    Matching is conservative and ordered: exact normalized name, then
    surname+initial signature (``Martinez L.`` vs ``Lautaro Martínez``), then
    a quotation that lists only the surname against a unique surname within
    the club. Each price row matches at most one roster row; surname
    collisions inside a club are reported as ambiguous instead of guessed.

    Returns a DataFrame with one row per price row: the roster index that
    matched (``-1`` when unmatched), the match type, and the roster status of
    the matched row (empty when unmatched).
    """
    result = pd.DataFrame(
        {
            "price_index": range(len(prices)),
            "roster_index": -1,
            "match_type": "unmatched",
            "roster_status": "",
        }
    )
    if roster.empty or prices.empty:
        return result

    club_key = club_column if club_column in roster.columns else "club"
    roster_norm = roster["player"].astype(str).map(normalize_name)
    roster_by_club: dict[str, list[int]] = {}
    for index in roster.index:
        roster_by_club.setdefault(str(roster.at[index, club_key]).strip(), []).append(index)

    claimed: dict[int, int] = {}
    for price_index, price_row in prices.iterrows():
        club = str(price_row.get("team", "")).strip().upper()
        club_name = FANTACALCIO_TEAM_CODES.get(club)
        if club_name is None:
            continue
        candidates = roster_by_club.get(club_name, [])
        if not candidates:
            continue
        price_name = str(price_row.get("player", ""))
        price_exact = normalize_name(price_name)
        price_signature = _surname_initial(price_name)
        price_surname, _ = _surname_tokens(price_name)
        price_tail = _surname_tail(price_name)
        exact = [i for i in candidates if roster_norm.at[i] == price_exact]
        if len(exact) == 1:
            match, match_type = exact[0], "exact"
        else:
            signature = [
                i for i in candidates
                if _surname_initial(str(roster.at[i, "player"])) == price_signature
            ]
            surname_only = price_exact == price_surname
            surnames = [
                i for i in candidates
                if _surname_tokens(str(roster.at[i, "player"]))[0] == price_surname
            ]
            tails = (
                [i for i in candidates if _surname_tail(str(roster.at[i, "player"])) == price_tail]
                if price_tail
                else []
            )
            if len(signature) == 1 and not (surname_only and len(surnames) > 1):
                match, match_type = signature[0], "surname_initial"
            elif surname_only and len(surnames) == 1:
                match, match_type = surnames[0], "surname_unique_in_club"
            elif len(tails) == 1:
                match, match_type = tails[0], "surname_tail_unique_in_club"
            else:
                continue
        if match in claimed.values():
            continue
        claimed[price_index] = match
        result.at[price_index, "roster_index"] = match
        result.at[price_index, "match_type"] = match_type
        result.at[price_index, "roster_status"] = str(roster.at[match, "status"])
    return result


def merge_current_prices(players_df: pd.DataFrame, prices_df: pd.DataFrame) -> pd.DataFrame:
    """Attach quotation roles and prices using conservative identity matching."""
    output = players_df.copy()
    if output.empty or prices_df.empty or "player" not in output.columns:
        return output
    if "player_normalized" not in output.columns:
        output["player_normalized"] = output["player"].map(normalize_name)
    if "role" in output.columns:
        output["role"] = output["role"].astype(object)

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
