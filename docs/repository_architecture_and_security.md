# Dual-Repository Architecture & IP Leak Prevention Guide

**Date:** August 2026  
**Subject:** Security blueprint, Dual-Repository (Public Core / Private Data) setup, automated leak prevention, and future merge procedures.

---

## 1. Overview & Security Objectives

This project contains two distinct categories of assets:
1. **Open-Source Code & Algorithms (Public):** Mathematical models (Sinh-Arcsinh, Bayesian confidence models, Monte Carlo optimization), research documentation, SQLite database schema DDL, pipeline orchestrator, and synthetic test suites.
2. **Proprietary & Licensed Data (Private):** Raw Excel vote files from Fantacalcio.it, scraper outputs, compiled SQLite databases containing third-party data, private auction strategies, and personal league configurations.

To protect intellectual property, prevent Terms of Service violations, and enable open-source collaboration, we establish a **Dual-Repository Pattern**.

---

## 2. Architecture: Public Core vs. Private Workspace

```
┌─────────────────────────────────────────────────────────┐
│                    PUBLIC REPOSITORY                    │
│          github.com/username/fantapredictor             │
│                                                         │
│  ├── src/                                               │
│  │   ├── models/ (SinhArcsinh, Bayesian, Optimizer)     │
│  │   ├── data_processing/ (Votes, Players, Matches)     │
│  │   ├── db/ (schema.sql, database.py)                  │
│  │   └── utils/ (name_matching.py, file_io.py)          │
│  ├── tests/ (100% mock & synthetic data tests)          │
│  ├── docs/ (Research notes, specs, architectures)       │
│  ├── .githooks/pre-commit (Automated leak blocker)      │
│  └── .gitignore (Strict data/db exclusions)             │
└────────────────────────────┬────────────────────────────┘
                             │
                             │ Included as Git Submodule / Subtree
                             ▼
┌─────────────────────────────────────────────────────────┐
│                    PRIVATE REPOSITORY                   │
│      github.com/username/fantapredictor-workspace       │
│                                                         │
│  ├── fantapredictor_core/ (Submodule of Public Repo)    │
│  ├── data/                                              │
│  │   ├── raw/ (Understat, Football-Data.co.uk dumps)    │
│  │   ├── fantacalcio/voti/ (Official weekly votes)      │
│  │   └── fantapredictor.db (Local SQLite warehouse)      │
│  ├── notebooks/ (Private auction strategy & exploratory)│
│  └── config/private_league_rules.json                   │
└─────────────────────────────────────────────────────────┘
```

---

## 3. Step-by-Step Setup Instructions

### Step 3.1. Setting Up the Public Repository
1. On GitHub, create a new **Public** repository named `fantapredictor`.
2. In your local repository:
   ```bash
   git remote add origin git@github.com:username/fantapredictor.git
   git branch -M main
   git push -u origin main
   ```

### Step 3.2. Setting Up the Private Repository
1. On GitHub, create a new **Private** repository named `fantapredictor-workspace`.
2. Initialize it locally and add the public core as a submodule:
   ```bash
   mkdir fantapredictor-workspace
   cd fantapredictor-workspace
   git init
   git submodule add git@github.com:username/fantapredictor.git fantapredictor_core
   git commit -m "Initialize private workspace with public fantapredictor submodule"
   git remote add origin git@github.com:username/fantapredictor-workspace.git
   git push -u origin main
   ```

### Step 3.3. Daily Development Workflow
- **When developing algorithms/models:** Work inside `fantapredictor_core/` (or the public repo), commit and push to public.
- **When running experiments with private data:** Run scripts from the private workspace pointing to local `data/` directories.
- **To update the private workspace with the latest public core:**
  ```bash
  cd fantapredictor-workspace
  git submodule update --remote --merge
  git commit -am "Update public fantapredictor submodule"
  git push origin main
  ```

---

## 4. Automated Leak Prevention & Data Hygiene

### 4.1. Pre-Commit Hook (`.githooks/pre-commit`)
Our public repository includes an automated pre-commit hook that runs on every commit:
- **Database Blocker:** Rejects staging of `*.db`, `*.sqlite`, `*.sqlite3`, `*.db-wal`, `*.db-shm`.
- **Spreadsheet/Data Blocker:** Rejects staging of `*.xlsx`, `*.xls`, `*.parquet`, and CSVs in data directories.
- **Secret & Token Scanner:** Detects API tokens (`ghp_`, `gho_`, `sk-`, AWS keys) and `.env` files.

**Activation Command:**
```bash
git config core.hooksPath .githooks
```

### 4.2. `.gitignore` Policy
The `.gitignore` configuration explicitly excludes all data artifacts, logs, compiled databases, and secrets:
```gitignore
# Data & spreadsheets
data/**
*.xlsx
*.xls
*.parquet

# Databases
*.db
*.db-wal
*.db-shm
*.sqlite
*.sqlite3

# Secrets
.env
*.key
*.pem
credentials.json
```

---

## 5. Future Merge Strategy: Consolidating Public & Private

If you ever wish to merge the two repositories in the future, follow these procedures:

### Option A: Standard Git Merge (if history is clean)
```bash
cd fantapredictor-workspace
git remote add public_repo git@github.com:username/fantapredictor.git
git fetch public_repo
git merge public_repo/main --allow-unrelated-histories -m "Merge public core into private repo"
```

### Option B: Purging Private Data Before Public Merge (`git-filter-repo`)
If private data was accidentally committed in the private history and you wish to make the combined repository public, purge historical data blobs first:
```bash
# 1. Install git-filter-repo
pip install git-filter-repo

# 2. Purge raw data and database files from entire commit graph
git filter-repo --path data/ --invert-paths
git filter-repo --path-glob '*.db' --invert-paths
git filter-repo --path-glob '*.xlsx' --invert-paths

# 3. Force push the sanitized branch
git push origin main --force
```
