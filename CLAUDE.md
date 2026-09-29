# FantaPredictor (public core)

## ⛔ Personal data: never push to GitHub

Never commit or push personal data to GitHub or any other remote, private repositories included: portfolio holdings, quantities, amounts, balances, ISINs, account or student IDs, broker exports, CVs, contracts, personal emails, credentials, API keys, `.env` files, private notes. Before every commit or push, review `git diff --cached` and every new file in `git status`; if anything looks personal, stop and ask the user.

This rule is about what leaves the machine, not about local work: tests, backtests, evaluations and verification runs executed locally must use the real data, otherwise the results are not truthful. Only committed content, test fixtures included, must be anonymized.

@AGENTS.md

Operational runbook for real data (auction day, refreshes, git flow) lives in
the private workspace: `fantapredictor-workspace/AGENTS.md`.
