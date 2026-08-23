# 2026/27 Defender Auction Analysis

**Snapshot:** current Fantacalcio.it quotation page and the latest three
available Understat Serie A seasons in the local snapshot.  
**Reproducible command:**

```bash
python scripts/download_current_prices.py --season 2026-27
python scripts/analyze_defenders.py
```

## Method

The analysis starts from classic role `D` in the current quotation snapshot.
Names are matched conservatively to Understat names using exact normalized
names, then surname plus first initial. Only players with recent evidence are
ranked. Recent production is calculated over the latest three available
seasons and shrunk with a 450-minute prior:

```text
xGI per 90 = 90 * (xG + xA) / (minutes + 450)
```

The production score combines xGI rate, realized goals/assists rate, and
availability percentile. An `undervalued` label is deliberately conservative:
current price must be `<= 8` credits and production must be at or above the
75th percentile of evidenced defenders. It is a value signal, not a guarantee
of starting status, transfer registration, or auction price.

## Shortlist

| Defender | Current price | Recent minutes | Goals + assists | xG + xA | View |
|---|---:|---:|---:|---:|---|
| Federico Dimarco | 32 | 4,557 | 23 | 25.23 | Premium elite; not undervalued |
| Raoul Bellanova | 6 | 5,960 | 17 | 17.50 | **Undervalued** |
| Carlos Augusto | 7 | 3,410 | 9 | 9.76 | **Undervalued** |
| Leonardo Spinazzola | 8 | 2,982 | 6 | 9.19 | **Undervalued**, fitness risk |
| Davide Zappacosta | 8 | 4,103 | 10 | 11.27 | **Undervalued** |
| Nadir Zortea | 6 | 4,360 | 15 | 10.98 | **Undervalued** |
| Emanuele Valeri | 8 | 4,416 | 9 | 11.65 | **Undervalued** |
| Cristiano Biraghi | 2 | 4,297 | 8 | 10.75 | **Undervalued**, verify transfer/role |
| Andrea Cambiaso | 9 | 4,812 | 10 | 11.43 | Strong, but just outside value label |
| Giovanni Di Lorenzo | 12 | 6,835 | 12 | 16.20 | Reliable premium; not undervalued |

## Interpretation

The strongest combination of production and price is Bellanova, Zortea,
Carlos Augusto, Valeri, Zappacosta, Spinazzola, and Biraghi. The first five
have substantial recent exposure; Spinazzola needs a fitness and probable-lineup
check, while Biraghi needs final club registration and role confirmation before
the auction.

The quotation snapshot and 2026/27 roster are time-sensitive. Re-run the
analysis after the transfer window closes and verify every player against the
official fantasy role list and probable starting role.
