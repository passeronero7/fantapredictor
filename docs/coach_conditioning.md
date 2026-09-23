# Coach conditioning

**Updated:** 23 September 2026 · code: `src/models/coach_profiles.py`,
`scripts/simulate_auction_propensity.py::coach_context`

## What it does

For every coach, the share of his teams' goals and assists that came from
defenders, midfielders and forwards, over every Serie A matchday he was in
charge of since 2015/16 (current season included). Shares are shrunk toward
the league share with 120 pseudo-goals (and 120 pseudo-assists).

Each player gets two multipliers:

    goal_mult = 1 + λ · (share now / mean share over his own history − 1)

and the same for assists. "Now" is the coach in charge at the first horizon
matchday; the history is every past rating row of the player, each with the
coach in charge that day. A player who keeps his coach stays at about 1; a
midfielder moving to a coach whose midfielders score more gains. In the
Monte Carlo the goal part (3 points per goal) and the assist part (1 point)
of each sampled bonus are rescaled, so the effect reaches
`expected_fantavoto` and the auction optimizer. Because the player's *own*
goals and assists are rescaled, a coach whose full-backs assist lifts the
defenders who already assist, not centre-backs with none.

Multipliers are capped at 0.6-1.6. Goalkeepers are not adjusted.

## Data

- `coaches/coach_history.csv` (workspace): 363 stints, 109 coaches,
  2015/16-2026/27, transcribed from the English Wikipedia season pages
  ("Managerial changes" and personnel tables) and checked for chain
  consistency (every outgoing coach is the previous incoming one; the last
  incoming coach is the season-end coach). 2026/27 in-season changes were
  confirmed on Italian press: Fiorentina, Grosso → Vanoli (6/7 September);
  Bologna, Tedesco → Palladino (16 September).
- Matches are attributed by date: a match belongs to the latest stint that
  started strictly before it. Rescheduled fixtures whose provider round
  differs from the official one take the nearest round's coach.
- Module and style tags of current coaches are descriptive only (the
  current module is taken from the latest probable XI).

## Validation

Season-ahead backtest (`backtest_coach_multipliers`): for each target season
2021/22-2025/26, profiles and player baselines use earlier data only; the
prediction is the player's per-appearance goal (assist) rate times the
multiplier; score is Poisson deviance over players with ≥15 appearances in
both history and target (1,317 player-seasons, 870 with a changed context).

| λ | goals | assists |
|---|---:|---:|
| 0 (off) | 3887.3 | 3329.9 |
| 0.25 | 3882.5 | 3328.3 |
| 0.5 | 3881.7 | 3329.3 |
| 1.0 | 3892.1 | 3339.1 |

(shrinkage 120). With the first five rounds of the target season observed,
as at this auction: 3518.7 → 3516.1 goals and 2941.7 → 2940.4 assists at
λ = 0.25; λ = 1.0 is worse (3528.3, 2950.7).

**Reading.** The coach effect on *who* scores is real but small: about 0.1%
of deviance. It helped in 2021/22-2023/24 and slightly hurt in 2024/25 and
2025/26. It is kept at λ = 0.25, where no season loses more than ~1.5
deviance points, and should be re-checked after the season. It does not
model changes in team *volume* (how many goals a coach's team scores);
that stays with the club style index.

## Not modelled

- Coaches with no Serie A history (Amorim, Aquilani, Abate) sit at the
  league share plus their first five matchdays.
- Vote (not bonus) effects of a coach, e.g. defensive solidity for the
  defence modifier.
- The club style multiplier in `simulate_horizon` can only reduce bonuses
  (acceptance probability capped at 1) and is applied on top of a history
  that already reflects the player's club: a known bias, not addressed here.
