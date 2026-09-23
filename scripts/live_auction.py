#!/usr/bin/env python3
"""Interactive live-auction console: log sales, re-plan, ask for maximum bids.

Every sale is appended to the state CSV (``giocatore,acquirente,prezzo``),
which is rewritten atomically after each command, so the session can be
closed and resumed at any time. Planning uses the same forecast, dossier and
MILP as ``optimize_auction_roster.py``; see ``src/models/live_auction.py``.

Commands (player names are matched ignoring case/accents; official ids work):

  q <giocatore>                 offerta massima per il giocatore chiamato
  m <giocatore> <prezzo>        l'ho preso io
  v <giocatore> <prezzo> <chi>  venduto a un altro partecipante
  p                             piano aggiornato
  b                             offerte massime per tutti gli obiettivi (lento)
  s                             crediti e slot dei partecipanti
  u                             annulla l'ultima aggiudicazione
  h                             aiuto
  x                             esci

Names with spaces need no quotes except for the buyer in ``v``, which is the
last token (use quotes for "Nome Cognome").
"""

from __future__ import annotations

import argparse
import os
import shlex
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.optimize_auction_roster import build_pool, calibrate_modifier
from src.models.auction_optimizer import AuctionOptimizationConfig
from src.models.live_auction import (
    STATE_COLUMNS,
    LivePlanner,
    manager_summary,
    read_state,
    resolve_player,
    resolve_state,
)

HELP = __doc__.split("Commands", 1)[1].split("\n", 1)[1].rsplit("Names with", 1)[0]


def write_state(state: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    state[STATE_COLUMNS].to_csv(tmp, index=False)
    os.replace(tmp, path)


def make_planner(args: argparse.Namespace) -> LivePlanner:
    pool, report = build_pool(args.forecast, args.dossier_players, args.defence_modifier,
                              args.quotation_floor)
    if report["unmatched_forecast"] or report["unmatched_dossier"]:
        print(f"attenzione: {len(report['unmatched_forecast'])} solo nel forecast, "
              f"{len(report['unmatched_dossier'])} solo nel dossier")
    marginal = AuctionOptimizationConfig.modifier_marginal
    if args.defence_modifier and args.db:
        marginal = calibrate_modifier(args.db, args.modifier_season)[
            "marginal_points_per_vote_point_per_player"]
    config = AuctionOptimizationConfig(
        budget=args.budget, reserve=args.reserve,
        defence_modifier=args.defence_modifier, modifier_marginal=marginal,
    )
    return LivePlanner(pool, config, me=args.me, managers=args.managers,
                       market_scaling=not args.no_market_scaling)


def show_plan(planner: LivePlanner, state: pd.DataFrame, previous: set | None = None) -> set:
    plan = planner.plan(state)
    roster = plan.roster
    current = set(roster["player"])
    print(roster[["role", "depth", "player", "team", "stato", "crediti",
                  "expected_fantavoto", "p_plays"]].to_string(index=False))
    spent_plan = int(roster["crediti"].sum())
    print(f"crediti rimasti {plan.my_budget_left}, offerta massima consentita "
          f"{plan.my_max_bid}; piano da {spent_plan} crediti "
          f"(tetto {planner.config.budget - planner.config.reserve}); "
          f"fattore di mercato {plan.market_factor:.2f}; "
          f"1 credito vale {plan.credit_value:.4f} punti-obiettivo; {plan.seconds:.1f} s")
    if previous is not None:
        entered, left = sorted(current - previous), sorted(previous - current)
        if entered or left:
            print(f"cambi nel piano: entrano {', '.join(entered) or '-'}; escono {', '.join(left) or '-'}")
    return current


def show_bid(planner: LivePlanner, state: pd.DataFrame, query: str) -> None:
    bid = planner.bid(state, query)
    status = "nel piano" if bid["nel_piano"] else "fuori piano"
    reason = f" ({bid['motivo']})" if bid["motivo"] else ""
    print(f"{bid['player']} ({bid['team']}, {bid['role']}) — {status}: "
          f"offerta massima {bid['offerta_max']}{reason}, riferimento {bid['riferimento']}")
    if bid["se_lo_perdi"]:
        print(f"  se lo perdi entrano: {bid['se_lo_perdi']}")
    sales = resolve_state(state, planner.full)
    managers = manager_summary(sales, planner.me, planner.managers, planner.config.budget)
    rivals = managers[~managers["acquirente"].eq(planner.me)
                      & managers[f"aperti_{bid['role']}"].gt(0)]
    if not rivals.empty:
        top = rivals.sort_values("offerta_max", ascending=False).head(3)
        print("  rivali con slot libero: " + ", ".join(
            f"{r.acquirente} fino a {r.offerta_max}" for r in top.itertuples()))
    print(f"  ({bid['secondi']} s)")


def parse_sale(tokens: list[str], mine: bool, me: str) -> dict:
    if mine:
        if len(tokens) < 2:
            raise ValueError("uso: m <giocatore> <prezzo>")
        name, price, buyer = " ".join(tokens[:-1]), tokens[-1], me
    else:
        if len(tokens) < 3:
            raise ValueError("uso: v <giocatore> <prezzo> <acquirente>")
        name, price, buyer = " ".join(tokens[:-2]), tokens[-2], tokens[-1]
    if not price.isdigit() or int(price) < 1:
        raise ValueError(f"prezzo non valido: {price}")
    return {"giocatore": name, "acquirente": buyer, "prezzo": int(price)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--forecast", type=Path, required=True)
    parser.add_argument("--dossier-players", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True, help="Auction log CSV (created if missing)")
    parser.add_argument("--me", default="io", help="Your name as buyer in the log")
    parser.add_argument("--managers", type=int, default=8)
    parser.add_argument("--budget", type=int, default=500)
    parser.add_argument("--reserve", type=int, default=0)
    parser.add_argument("--defence-modifier", action="store_true")
    parser.add_argument("--quotation-floor", type=float, default=0.5)
    parser.add_argument("--db", type=Path)
    parser.add_argument("--modifier-season", default="2025/26")
    parser.add_argument("--no-market-scaling", action="store_true",
                        help="Keep dossier reference prices instead of rescaling the unsold "
                             "players to the money left in the league")
    parser.add_argument("--command", action="append",
                        help="Run these commands and exit (repeatable), e.g. --command 'q Thuram'")
    args = parser.parse_args()

    planner = make_planner(args)
    state = read_state(args.state)
    resolve_state(state, planner.full)  # fail early on a bad log
    print(f"stato: {len(state)} aggiudicazioni in {args.state}")
    current = show_plan(planner, state)

    commands = iter(args.command) if args.command else None
    while True:
        try:
            line = next(commands) if commands else input("\nasta> ")
        except (EOFError, StopIteration):
            break
        try:
            tokens = shlex.split(line)
        except ValueError as exc:
            print(f"errore: {exc}")
            continue
        if not tokens:
            continue
        verb, rest = tokens[0].lower(), tokens[1:]
        try:
            if verb in {"x", "exit", "quit"}:
                break
            if verb in {"h", "help", "?"}:
                print(HELP)
            elif verb == "q":
                show_bid(planner, state, " ".join(rest))
            elif verb in {"m", "v"}:
                sale = parse_sale(rest, verb == "m", args.me)
                row = resolve_player(sale["giocatore"], planner.full)
                sale["giocatore"] = planner.full.at[row, "player"]
                candidate = pd.concat([state, pd.DataFrame([sale])], ignore_index=True)
                # Validates double sales, slots per role and budgets.
                manager_summary(resolve_state(candidate, planner.full), planner.me,
                                planner.managers, planner.config.budget)
                state = candidate
                write_state(state, args.state)
                print(f"registrato: {sale['giocatore']} a {sale['acquirente']} per {sale['prezzo']}")
                current = show_plan(planner, state, current)
            elif verb == "u":
                if state.empty:
                    print("niente da annullare")
                    continue
                last = state.iloc[-1]
                state = state.iloc[:-1].reset_index(drop=True)
                write_state(state, args.state)
                print(f"annullato: {last['giocatore']} ({last['acquirente']}, {last['prezzo']})")
                current = show_plan(planner, state, current)
            elif verb == "p":
                current = show_plan(planner, state, current)
            elif verb == "b":
                table = planner.plan_bids(state)
                print(table[["player", "team", "role", "riferimento", "offerta_max",
                             "motivo", "se_lo_perdi"]].to_string(index=False))
            elif verb == "s":
                print(manager_summary(resolve_state(state, planner.full), planner.me,
                                      planner.managers, planner.config.budget).to_string(index=False))
            else:
                print(f"comando sconosciuto '{verb}' (h per l'aiuto)")
        except (KeyError, ValueError) as exc:
            print(f"errore: {exc.args[0] if exc.args else exc}")


if __name__ == "__main__":
    main()
