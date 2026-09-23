"""Coach and club tendencies: who scores and who assists under each coach.

The propensity simulation bootstraps each player's own past marks, so his
bonus rate already reflects the contexts he played in. What changes at an
auction is the *context*: a new coach (Fiorentina, Bologna this season), a
transfer, or a coach whose system feeds a different role. This module turns
that into two multipliers per player:

- ``goal_mult``: how much of his club's goals his role is expected to score
  under the current coach, relative to the coaches he produced his history
  under;
- ``assist_mult``: the same for assists.

Coach profiles are the share of a team's goals (and assists) scored by
defenders, midfielders and forwards in every Serie A matchday the coach was
in charge of, shrunk toward the league share. Scaling each player's own
goals/assists (rather than a role-wide bonus) keeps the effect on the right
sub-role: a coach whose full-backs assist a lot lifts the defenders who
already assist, not centre-backs with none. The current season's matchdays
under the current coach are part of his profile, so a club's early trend
enters with the same shrinkage.

The strength of the adjustment (``DEFAULT_LAMBDA``) and the shrinkage
(``DEFAULT_SHRINKAGE``) come from :func:`backtest_coach_multipliers`, a
season-ahead check on 2021/22-2025/26: see ``docs/coach_conditioning.md``.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

import numpy as np
import pandas as pd

ROLES = ("D", "C", "A")
# Pseudo-counts (in goals, and in assists) pulling a coach's role share toward
# the league share: about two and a half seasons of a team's goals.
DEFAULT_SHRINKAGE = 120.0
# Fraction of the raw context ratio applied (0 = off, 1 = full ratio). The
# season-ahead backtest (2021/22-2025/26, with and without five observed
# rounds) is best at 0.25-0.5 and clearly worse at 1.0; the effect is small.
DEFAULT_LAMBDA = 0.25
MULTIPLIER_CAP = (0.6, 1.6)


def coach_matchdays(conn: sqlite3.Connection) -> pd.DataFrame:
    """One row per (season, club, matchday) with the coach in charge.

    Stints come from ``coach_club_seasons``; match dates from ``matches``.
    A match belongs to the latest stint that started strictly before its
    date (a coach sacked on the day of a match coached that match), or to
    the season's first stint.
    """
    stints = pd.read_sql_query(
        """
        SELECT s.name AS season, c.name AS club, co.full_name AS coach,
               ccs.started_at
        FROM coach_club_seasons AS ccs
        JOIN coaches AS co ON co.id = ccs.coach_id
        JOIN clubs AS c ON c.id = ccs.club_id
        JOIN seasons AS s ON s.id = ccs.season_id
        """,
        conn,
    )
    if stints.empty:
        return pd.DataFrame(columns=["season", "club", "matchday", "coach"])
    matches = pd.read_sql_query(
        """
        SELECT s.name AS season, m.matchday, date(m.match_date) AS match_date,
               h.name AS home, a.name AS away
        FROM matches AS m
        JOIN seasons AS s ON s.id = m.season_id
        JOIN clubs AS h ON h.id = m.home_club_id
        JOIN clubs AS a ON a.id = m.away_club_id
        WHERE m.matchday IS NOT NULL
        """,
        conn,
    )
    sides = pd.concat([
        matches.rename(columns={"home": "club"})[["season", "matchday", "match_date", "club"]],
        matches.rename(columns={"away": "club"})[["season", "matchday", "match_date", "club"]],
    ])
    # Several providers can carry the same fixture; one date per club-round.
    sides = sides.sort_values("match_date").drop_duplicates(["season", "club", "matchday"])
    stints = stints.sort_values("started_at", na_position="first")
    by_club = {key: block for key, block in stints.groupby(["season", "club"])}
    coaches = []
    for season, club, match_date in zip(sides["season"], sides["club"], sides["match_date"]):
        block = by_club.get((season, club))
        if block is None:
            coaches.append(None)
            continue
        started = block["started_at"].fillna("")
        earlier = block[started < match_date]
        coaches.append((earlier if len(earlier) else block).iloc[-1 if len(earlier) else 0]["coach"])
    sides["coach"] = coaches
    sides = sides.dropna(subset=["coach"])
    # Provider round numbers can disagree with the official round for
    # rescheduled fixtures, leaving holes; a hole takes the coach of the
    # nearest round the club did play under the same numbering.
    filled = []
    for (season, club), block in sides.groupby(["season", "club"]):
        rounds = pd.RangeIndex(1, int(block["matchday"].max()) + 1, name="matchday")
        coach = block.set_index("matchday")["coach"].reindex(rounds).ffill().bfill()
        filled.append(pd.DataFrame({"season": season, "club": club,
                                    "matchday": rounds, "coach": coach.to_numpy()}))
    return pd.concat(filled, ignore_index=True)


def attach_coach(ratings: pd.DataFrame, matchdays: pd.DataFrame) -> pd.DataFrame:
    """Add the coach in charge to rating rows (``season``, ``team``, ``matchday``)."""
    # Club spellings differ in case between providers ("SPAL"/"Spal").
    keyed = matchdays.assign(team_key=matchdays["club"].str.casefold())[
        ["season", "team_key", "matchday", "coach"]
    ]
    frame = ratings.copy()
    frame["matchday"] = pd.to_numeric(frame["matchday"], errors="coerce")
    frame["team_key"] = frame["team"].astype(str).str.casefold()
    return frame.merge(keyed, on=["season", "team_key", "matchday"], how="left").drop(columns="team_key")


@dataclass
class CoachProfiles:
    """Shrunk role shares of goals and assists, per coach."""

    goal_share: pd.DataFrame  # index coach, columns ROLES
    assist_share: pd.DataFrame
    league_goal_share: pd.Series
    league_assist_share: pd.Series
    matchdays: pd.Series  # matchdays in charge, per coach

    def share(self, kind: str, coach: str | None, role: str) -> float:
        table = self.goal_share if kind == "goal" else self.assist_share
        league = self.league_goal_share if kind == "goal" else self.league_assist_share
        if coach is not None and coach in table.index and role in table.columns:
            return float(table.at[coach, role])
        return float(league.get(role, np.nan))


def coach_profiles(rated: pd.DataFrame, shrinkage: float = DEFAULT_SHRINKAGE) -> CoachProfiles:
    """Role shares of goals and assists per coach, shrunk toward the league.

    ``rated`` needs ``coach``, ``role``, ``goals`` and ``assists``.
    Goalkeepers are excluded from the shares.
    """
    frame = rated.dropna(subset=["coach"])
    frame = frame[frame["role"].isin(ROLES)]
    goals = frame.pivot_table(index="coach", columns="role", values="goals", aggfunc="sum", fill_value=0)
    assists = frame.pivot_table(index="coach", columns="role", values="assists", aggfunc="sum", fill_value=0)
    goals = goals.reindex(columns=list(ROLES), fill_value=0)
    assists = assists.reindex(columns=list(ROLES), fill_value=0)
    league_goals = goals.sum() / max(goals.values.sum(), 1)
    league_assists = assists.sum() / max(assists.values.sum(), 1)

    def shrink(counts: pd.DataFrame, league: pd.Series) -> pd.DataFrame:
        total = counts.sum(axis=1)
        return (counts + shrinkage * league).div(total + shrinkage, axis=0)

    days = frame.drop_duplicates(["season", "team", "matchday"]).groupby("coach").size()
    return CoachProfiles(
        goal_share=shrink(goals, league_goals),
        assist_share=shrink(assists, league_assists),
        league_goal_share=league_goals,
        league_assist_share=league_assists,
        matchdays=days,
    )


def context_multipliers(
    history: pd.DataFrame,
    profiles: CoachProfiles,
    current: pd.DataFrame,
    strength: float = DEFAULT_LAMBDA,
) -> pd.DataFrame:
    """Per-player goal/assist multipliers for a change of coaching context.

    ``history``: the player's past rating rows with ``player_normalized``,
    ``role``, ``coach`` (rows without a known coach use the league share).
    ``current``: ``player_normalized``, ``role`` and ``coach`` now in charge.
    ``multiplier = 1 + strength * (share_now / mean share in history - 1)``.
    """
    rows = history[history["role"].isin(ROLES)]
    records = []
    past = {key: block for key, block in rows.groupby("player_normalized")}
    for key, role, coach in zip(current["player_normalized"], current["role"], current["coach"]):
        record = {"player_normalized": key, "goal_mult": 1.0, "assist_mult": 1.0,
                  "coach": coach}
        block = past.get(key)
        if role in ROLES and block is not None and len(block):
            for kind in ("goal", "assist"):
                then = np.mean([profiles.share(kind, c if isinstance(c, str) else None, role)
                                for c in block["coach"]])
                now = profiles.share(kind, coach if isinstance(coach, str) else None, role)
                if then > 0 and np.isfinite(now):
                    raw = 1.0 + strength * (now / then - 1.0)
                    record[f"{kind}_mult"] = float(np.clip(raw, *MULTIPLIER_CAP))
        records.append(record)
    return pd.DataFrame(records)


def backtest_coach_multipliers(
    rated: pd.DataFrame,
    target_seasons: list[str],
    strengths: tuple[float, ...] = (0.0, 0.25, 0.5, 0.75, 1.0),
    shrinkages: tuple[float, ...] = (30.0, 60.0, 120.0),
    min_history: int = 15,
    min_target: int = 15,
    observed_rounds: int = 0,
) -> pd.DataFrame:
    """Season-ahead check: does the coach context improve goal/assist rates?

    For every target season, profiles use only earlier seasons; each player's
    baseline is his per-appearance goal and assist rate over all earlier
    seasons, the "current coach" is his club's coach at the target season's
    first matchday. Scored on per-appearance Poisson deviance of goals and
    assists in the target season (lower is better), over all qualifying
    players and over the subset whose coaching context changed.

    ``observed_rounds`` reproduces the auction situation: the first rounds
    of the target season are already known (they feed both the profiles and
    the players' baselines) and only the later rounds are scored; the
    "current coach" is then the one in charge at the last observed round.
    """
    results = []
    frame = rated[rated["role"].isin(ROLES)].dropna(subset=["coach"])
    for shrinkage in shrinkages:
        for season in target_seasons:
            in_season = frame["season"] == season
            known = frame["season"].lt(season) | (in_season & frame["matchday"].le(observed_rounds))
            before = frame[known]
            during = frame[in_season & frame["matchday"].gt(observed_rounds)]
            profiles = coach_profiles(before, shrinkage=shrinkage)
            reference = before[before["season"] == season] if observed_rounds else during
            if reference.empty:
                reference = during
            pick = reference.groupby("team")["matchday"].transform("max" if observed_rounds else "min")
            opening = reference[reference["matchday"].eq(pick)].drop_duplicates("team")
            coach_now = dict(zip(opening["team"], opening["coach"]))
            target = during.groupby("player_normalized").agg(
                apps=("goals", "size"), goals=("goals", "sum"), assists=("assists", "sum"),
                team=("team", "first"), role=("role", "first"),
            )
            base = before.groupby("player_normalized").agg(
                apps=("goals", "size"), goals=("goals", "sum"), assists=("assists", "sum"),
            )
            players = target.join(base, rsuffix="_hist", how="inner")
            players = players[(players["apps"] >= min_target) & (players["apps_hist"] >= min_history)]
            if players.empty:
                continue
            current = pd.DataFrame({
                "player_normalized": players.index,
                "role": players["role"].to_numpy(),
                "coach": [coach_now.get(t) for t in players["team"]],
            })
            hist = before[before["player_normalized"].isin(players.index)]
            full = context_multipliers(hist, profiles, current, strength=1.0).set_index("player_normalized")
            changed = ((full["goal_mult"] - 1).abs() > 0.1) | ((full["assist_mult"] - 1).abs() > 0.1)
            for strength in strengths:
                score = {"season": season, "shrinkage": shrinkage, "strength": strength,
                         "players": int(len(players)), "changed": int(changed.sum())}
                for kind, column in (("goal", "goals"), ("assist", "assists")):
                    rate = players[column + "_hist"] / players["apps_hist"]
                    mult = 1.0 + strength * (full.loc[players.index, f"{kind}_mult"] - 1.0)
                    predicted = (rate * mult).clip(lower=1e-4) * players["apps"]
                    observed = players[column]
                    deviance = 2 * (
                        np.where(observed > 0, observed * np.log(observed / predicted), 0.0)
                        - (observed - predicted)
                    )
                    deviance = pd.Series(deviance, index=players.index)
                    score[f"{kind}_deviance"] = float(deviance.sum())
                    score[f"{kind}_deviance_changed"] = float(deviance[changed.to_numpy()].sum())
                results.append(score)
    return pd.DataFrame(results)
