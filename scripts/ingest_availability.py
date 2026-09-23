#!/usr/bin/env python3
"""Ingest the curated availability (injury/stop) CSV into the warehouse."""
import argparse, calendar, re, sys
from datetime import date
from pathlib import Path
import pandas as pd
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from config.settings import config
from src.db import database
from src.db.ingestors.common import player_id

def load(conn, path: Path) -> int:
    frame = pd.read_csv(path)
    for row in frame.to_dict("records"):
        pid = player_id(conn, str(row["player"]), "leaf-node-manual")
        conn.execute(
            """INSERT INTO availability_notes (player_id, club, kind, expected_return, source_url, checked_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(player_id, kind) DO UPDATE SET club=excluded.club,
                 expected_return=excluded.expected_return, source_url=excluded.source_url,
                 checked_at=excluded.checked_at""",
            (pid, row.get("club"), row["kind"], row.get("expected_return"),
             row.get("source_url"), row.get("checked_at")),
        )
    conn.commit()
    return len(frame)

MONTHS = {name: number for number, name in enumerate(
    ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio",
     "agosto", "settembre", "ottobre", "novembre", "dicembre"], start=1)}
# Return-context words: a date phrase counts only when it follows one of
# these (within RETURN_WINDOW characters), so injury dates ("KO a gennaio",
# "operato a fine giugno") are not mistaken for return dates.
RETURN_WORDS = re.compile(
    r"rientr|torna|recuper|rivederlo|arruolabil|convocabil|ritorno|in campo|ai box", re.I)
RETURN_WINDOW = 80
# Longest phrases first so "seconda metà" is not read as "metà".
DATE_PHRASES = [
    (re.compile(r"prima met[aà] di (\w+)"), 8),
    (re.compile(r"seconda met[aà] di (\w+)"), 20),
    (re.compile(r"met[aà] (?:di )?(\w+)"), 15),
    (re.compile(r"fine (?:di )?(\w+)"), "last"),
    (re.compile(r"inizio (?:di )?(\w+)"), 1),
    (re.compile(r"\bda (\w+)"), 1),
    (re.compile(r"\bdal mese di (\w+)"), 1),
]


def derive_return_date(note: str, as_of: date) -> date | None:
    """Return date from an explicit window in the source note, else None.

    Documented rule (AGENTS.md): "prima metà" = 8, "seconda metà" = 20,
    "metà" = 15, "fine" = last day, "inizio" and "da <mese>" = 1st. The
    month is taken in the coming twelve months from ``as_of``; phrases
    before ``as_of`` and phrases not preceded by a return word are ignored.
    Vague notes ("da valutare", "prossimo turno") stay undated.
    """
    text = str(note or "").lower()
    found: list[tuple[int, date]] = []
    taken: list[tuple[int, int]] = []
    for pattern, day in DATE_PHRASES:
        for match in pattern.finditer(text):
            if any(start <= match.start() < end for start, end in taken):
                continue
            month = MONTHS.get(match.group(1))
            if month is None:
                continue
            taken.append((match.start(), match.end()))
            year = as_of.year if month >= as_of.month else as_of.year + 1
            last = calendar.monthrange(year, month)[1]
            value = date(year, month, last if day == "last" else day)
            before = text[max(0, match.start() - RETURN_WINDOW):match.start()]
            if value >= as_of and RETURN_WORDS.search(before):
                found.append((match.start(), value))
    return min(found)[1] if found else None


def derive_dates(frame: pd.DataFrame, as_of: date, overwrite: bool = False) -> pd.DataFrame:
    """Fill ``expected_return`` from each note (only empty cells unless overwrite)."""
    frame = frame.copy()
    frame["expected_return"] = frame["expected_return"].astype(object)
    for index, row in frame.iterrows():
        if not overwrite and pd.notna(row["expected_return"]) and str(row["expected_return"]).strip():
            continue
        derived = derive_return_date(row.get("note", ""), as_of)
        frame.at[index, "expected_return"] = derived.isoformat() if derived else None
    return frame


def horizon_factor(expected_return: str, horizon_start: date, horizon_days: int) -> float:
    """Fraction of the horizon the player is available, as a p_plays multiplier."""
    try:
        ret = date.fromisoformat(str(expected_return)[:10])
    except (TypeError, ValueError):
        return 1.0
    if ret <= horizon_start:
        return 1.0
    missed = (ret - horizon_start).days
    return max(0.0, 1.0 - min(missed, horizon_days) / max(horizon_days, 1))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=config.DATA_DIR / "fantapredictor.db")
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--derive-dates", action="store_true",
                        help="Fill empty expected_return cells from the note text (rule in "
                             "derive_return_date) and rewrite the CSV before ingesting")
    parser.add_argument("--overwrite-dates", action="store_true",
                        help="With --derive-dates: recompute every date, not only empty ones")
    parser.add_argument("--as-of", default=None, help="Reference date for --derive-dates (ISO; default today)")
    args = parser.parse_args()
    if args.derive_dates:
        as_of = date.fromisoformat(args.as_of) if args.as_of else date.today()
        frame = derive_dates(pd.read_csv(args.csv), as_of, overwrite=args.overwrite_dates)
        frame.to_csv(args.csv, index=False)
        print(f"return dates: {int(frame['expected_return'].notna().sum())} of {len(frame)} dated "
              f"(as of {as_of.isoformat()})")
    conn = database.get_connection(args.db)
    database.init_schema(conn)
    try:
        print(f"availability rows loaded: {load(conn, args.csv)}")
    finally:
        conn.close()
