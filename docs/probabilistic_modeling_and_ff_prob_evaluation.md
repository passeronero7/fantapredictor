# Probabilistic Modeling for Fantacalcio: Evaluation & Adaptation of `ff_prob`

**Date:** August 2026  
**Subject:** Technical evaluation of `amiles2233/ff_prob` (NFL Probabilistic Modeling) and its adaptation to Serie A Fantacalcio 2026/27.

---

## 1. Executive Summary

`amiles2233/ff_prob` is an open-source framework developed for Daily Fantasy Football (NFL) and sports betting using TensorFlow Probability (`tfprobability`). Its core philosophy replaces point-estimate predictions ($\hat{y}$) with full probability density functions ($p(y|\mathbf{x})$) parameterized by flexible, asymmetric distributions (specifically **Sinh-Arcsinh** / SHASH).

This document evaluates the applicability of `ff_prob` concepts to Italian Fantacalcio (Serie A), contrasts the statistical dynamics of NFL vs. Association Football (Soccer), and specifies the mathematical and architectural blueprint for integrating probabilistic modeling into our pipeline.

---

## 2. Core Concepts from `ff_prob`

### 2.1. Top-Down Hierarchical Conditioning (Game Context First)
In sports modeling, predicting individual player outputs directly from past player averages produces high variance and fails to capture game-level dynamics. `ff_prob` implements a top-down paradigm:

1. **Macro Level (Match Outcome):** Model the distribution of match-level events (total points, spread, pace).
2. **Micro Level (Player Performance):** Model player fantasy scoring *conditioned* on the match outcome and team share.

**Advantage:** Leveraging bookmaker consensus lines (e.g., Over/Under 2.5, Asian handicap) provides an informative prior grounded in market efficiency.

### 2.2. Sinh-Arcsinh (SHASH) Probabilistic Distribution
Sports performance distributions are non-Gaussian:
- **Right-skewed:** Attackers frequently score around average (e.g. pure grade 6.0) with a long right tail of explosive multi-goal games (+3/+6 bonus points).
- **Fat-tailed (heavy kurtosis):** Rare events (hat-tricks, red cards, penalty saves) occur more often than Gaussian tails predict.

The Sinh-Arcsinh transformation (Jones & Pewsey, 2009) parameterizes a standard normal variable $Z \sim \mathcal{N}(0, 1)$ via:
$$Y = \mu + \sigma \sinh\left( \frac{\operatorname{asinh}(Z) + \epsilon}{\delta} \right)$$
Where:
- $\mu \in \mathbb{R}$ is the **location** (central tendency).
- $\sigma > 0$ is the **scale** (dispersion).
- $\epsilon \in \mathbb{R}$ is the **skewness** ($\epsilon > 0$ for right-skew, $\epsilon < 0$ for left-skew).
- $\delta > 0$ is the **tailweight** ($\delta < 1$ for heavy tails / high kurtosis, $\delta > 1$ for thin tails).

### 2.3. Monte Carlo Simulation for Lineup Optimization
Rather than choosing fantasy lineups based on expected value $\mathbb{E}[Y_i]$, `ff_prob` draws $N$ joint simulations across the slate:
- Calculates ceiling outcomes (e.g., 90th percentile $\mathcal{Q}_{0.90}$).
- Models correlation (e.g., Goalkeeper clean sheet correlated with Defender grades, Striker goals correlated with Midfielder assists).
- Optimizes tactical lineups under constraints (budget, formation, league rules).

---

## 3. Comparative Analysis: NFL DFS vs. Serie A Fantacalcio

| Dimension | NFL Fantasy (`ff_prob`) | Serie A Fantacalcio (Our Project) |
|---|---|---|
| **Event Frequency** | High-scoring (~45 total points/game) | Low-scoring (~2.5 goals/game) |
| **Scoring Structure** | Purely continuous aggregate stats (yards, completions, TDs) | Composite: Base Grade (*Voto puro*, 5.0–8.0) + Discrete Bonuses/Maluses (+3 goal, +1 assist, -0.5 yellow, -1 red, -1 goal conceded) |
| **Goalkeeper/Defensive Rules** | Team Defense/Special Teams (DST) unit | Individual GK rating + goals conceded (-1) + penalty saves (+3) + *Modificatore Difesa* |
| **Market Information** | Spread line + Over/Under total points | 1X2 odds, Asian handicap, Over/Under 2.5, Clean Sheet odds |
| **Tactical Formation** | Fixed positions (1 QB, 2 RB, 3 WR, 1 TE, 1 FLEX) | Flexible formations (3-4-3, 3-5-2, 4-3-3, 4-4-2, 4-5-1, etc.) with bench substitutions |

---

## 4. Adaptation Strategy for Fantacalcio

### 4.1. Two-Stage Composite Scoring Model
In Fantacalcio, the *Fantavoto* ($FV$) is defined as:
$$FV_i = V_i + \sum_k w_k \cdot E_{i,k}$$
Where $V_i$ is the base subjective journalist/algorithmic grade (typically $\mu \approx 6.0$, $\sigma \approx 0.6$), and $E_{i,k}$ are discrete event counts with weights $w_k$.

We adapt the probabilistic paradigm into two complementary options:
1. **Direct Sinh-Arcsinh Modeling of $FV$:** Fit a 4-parameter SHASH distribution directly on historical $FV$ conditioned on player position, recency-weighted stats, and match odds.
2. **Two-Stage Hurdle / Poisson-Gamma Mixture:**
   - Base Grade $V \sim \operatorname{TruncatedNormal}(6.0, \sigma^2)$ or $\operatorname{SHASH}(\mu_v, \sigma_v, \epsilon_v, \delta_v)$.
   - Goal Events $G \sim \operatorname{Poisson}(\lambda_g)$ where $\lambda_g = \text{xG}_{player} \cdot f(\text{Opponent Defence})$.
   - Assist Events $A \sim \operatorname{Poisson}(\lambda_a)$ where $\lambda_a = \text{xA}_{player} \cdot f(\text{Match Tempo})$.
   - Cards $C \sim \operatorname{Bernoulli}(p_c)$.

### 4.2. Game Context Features from Betting Data
Using `football-data.co.uk` and Understat match stats:
- **Implied Team Expected Goals:** $\lambda_{\text{team}} = -\ln(P(\text{Team Clean Sheet}))$.
- **Match Tempo / Over/Under Odds:** Implied probability of high-scoring game ($> 2.5$ goals).
- **Home Advantage Weight:** Derived from historical home vs away win probabilities.

### 4.3. Lineup Optimization with Monte Carlo Simulation
- **Objective:** Maximize $\sum_{j \in \text{Lineup}} FV_j^{(s)}$ across $S = 10{,}000$ draws.
- **Rule Modifiers:** Compute *Modificatore di Difesa* dynamically for each draw:
  - Average rating of GK + top 3 Defenders $\ge 6.0 \implies +1$ to $+6$ bonus points.
- **Formation Selection:** Evaluates best formation per simulation draw to find robust rosters.

---

## 5. Architectural Blueprint

```
fantapredictor/
├── src/
│   ├── models/
│   │   ├── confidence_model.py     # Empirical-Bayes pre-season baseline (implemented)
│   │   ├── distributions.py        # Sinh-Arcsinh and parametric distribution utilities
│   │   ├── neural_network.py       # Probabilistic predictor for Fantavoto
│   │   └── lineup_optimizer.py     # Monte Carlo lineup optimizer
│   ├── data_processing/
│   │   ├── votes_processor.py      # Fantacalcio.it weekly votes importer
│   │   ├── players_processor.py    # Multi-source player merger
│   │   └── match_data_builder.py   # Training feature matrix generator
│   └── db/
│       ├── database.py             # SQLite research warehouse connection & schema
│       └── ingestors/              # Provider ingestion pipelines
```
