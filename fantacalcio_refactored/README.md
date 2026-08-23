# Fantacalcio - Bayesian Estimated Team's Outcome

Machine learning model for predicting Serie A players' performance in Fantacalcio (Italian fantasy football).

**Refactored codebase** - modular, maintainable, and production-ready.

## 🎯 Project Goal

Predict Fantacalcio player performances (vote and fantavote) using:
- Player and team statistics from [FBRef.com](http://fbref.com)
- Historical vote data from [Fantacalcio.it](http://fantacalcio.it)
- Bayesian Neural Networks with probability distributions

## 📁 Project Structure

```
fantacalcio/
├── config/
│   └── settings.py          # Centralized configuration
├── src/
│   ├── scrapers/
│   │   ├── fbref_scraper.py          # FBRef data scraping
│   │   └── fantacalcio_scraper.py    # Fantacalcio scraping
│   ├── data_processing/
│   │   ├── votes_processor.py        # Vote data processing
│   │   ├── players_processor.py      # Player data merging
│   │   └── match_data_builder.py     # Training dataset creation
│   ├── models/
│   │   ├── neural_network.py         # Bayesian NN implementation
│   │   └── lineup_optimizer.py       # Lineup optimization
│   └── utils/
│       ├── name_matching.py          # Name normalization
│       └── file_io.py                # File I/O utilities
├── notebooks/
│   └── [exploration notebooks]       # Optional analysis
├── scripts/
│   ├── run_pipeline.py               # Main pipeline orchestrator
│   └── cli.py                        # Command-line interface
├── data/
│   ├── fbref_data/                   # Scraped FBRef data
│   ├── fantacalcio/                  # Fantacalcio data
│   ├── mid_outputs/                  # Intermediate outputs
│   └── outputs/                      # Final predictions
└── tests/
    └── [unit tests]
```

## 🚀 Quick Start

### Installation

```bash
# Install dependencies
pip install -r requirements.txt

# Or install specific packages
pip install pandas numpy tensorflow tensorflow-probability \
            scikit-learn requests beautifulsoup4 lxml openpyxl
```

### Basic Usage

#### Option 1: Run Full Pipeline (Automated)

```bash
# Run complete pipeline for current season
python scripts/run_pipeline.py --season 2324

# Run with historical seasons for training
python scripts/run_pipeline.py --season 2324 --include-history
```

#### Option 2: Step-by-Step Execution

```python
from src.scrapers.fbref_scraper import FBRefScraper
from src.data_processing.players_processor import PlayersProcessor
from src.models.neural_network import FantacalcioPredictor

# 1. Scrape data
scraper = FBRefScraper()
data = scraper.scrape_all(save_dir='data/fbref_data')

# 2. Process players
processor = PlayersProcessor()
players_df = processor.merge_all_sources()

# 3. Train model
predictor = FantacalcioPredictor()
predictor.train(training_data)

# 4. Generate predictions
predictions = predictor.predict_matchday(matchday=15)
```

#### Option 3: Command-Line Interface

```bash
# Scrape current season data
python -m fantacalcio scrape --season 2324

# Train model
python -m fantacalcio train --use-old-seasons

# Generate predictions for next matchday
python -m fantacalcio predict --matchday 15

# Optimize lineup
python -m fantacalcio optimize-lineup --budget 500 --formation 3-4-3
```

## 📊 Data Pipeline

### Pipeline Stages

1. **Data Scraping** (`scripts/01_scrape_data.py`)
   - FBRef: Player and team statistics
   - Fantacalcio: Votes, quotazioni, probable lineups

2. **Vote Processing** (`scripts/02_process_votes.py`)
   - Parse weekly vote files
   - Link to Serie A calendar
   - Generate players_votes.xlsx

3. **Player Data Merging** (`scripts/03_merge_players.py`)
   - Combine FBRef stats with Fantacalcio data
   - Handle name matching and normalization
   - Generate players_stats.xlsx

4. **Training Dataset Creation** (`scripts/04_build_training_data.py`)
   - Create player-match entries
   - Combine player stats + team stats + opponent stats
   - Generate database_entries.xlsx

5. **Model Training** (`scripts/05_train_model.py`)
   - Train Bayesian Neural Networks
   - Separate models for outfield players and goalkeepers
   - Output: SinhArcsinh distribution parameters

6. **Prediction Generation** (`scripts/06_generate_predictions.py`)
   - Predict for upcoming matchday
   - Account for probable lineups
   - Output: prediction Excel files

7. **Lineup Optimization** (`scripts/07_optimize_lineup.py`)
   - Monte Carlo simulation
   - Budget and formation constraints
   - Expected points maximization

## 🧠 Model Architecture

### Bayesian Neural Network

- **Framework**: TensorFlow + TensorFlow Probability
- **Architecture**: Configurable layers (default: 128-128-64)
- **Output Distribution**: SinhArcsinh (skewed, handles extreme values)
- **Separate Models**:
  - Outfield players: Vote + Fantavote distributions
  - Goalkeepers: Vote + Fantavote + Clean sheet probability

### Why SinhArcsinh Distribution?

Traditional Gaussian distributions assume symmetry, but player performances are often skewed:
- Attacking players: Higher probability of exceptional performance (goals/assists)
- Defensive players: More concentrated around average

SinhArcsinh captures this asymmetry with 4 parameters:
- Location (μ): Mean
- Scale (σ): Spread
- Skewness (ε): Asymmetry
- Tailweight (δ): Extreme value likelihood

## 📈 Key Features

### Configuration Management
All settings in `config/settings.py`:
- File paths
- URLs
- Model hyperparameters
- Feature lists

### Name Matching
Robust player name matching between sources:
- Accent normalization
- Special character handling
- Manual fixes support
- Team name standardization

### Data Validation
Comprehensive validation at each stage:
- Missing data checks
- Range validation
- Consistency verification

### Caching
File-based caching for expensive operations:
- Scraped data
- Processed datasets
- Model predictions

## 🔧 Configuration

Edit `config/settings.py` to customize:

```python
# Season configuration
CURRENT_SEASON = '2324'
HISTORICAL_SEASONS = ['2021', '2122', '2223']

# Model hyperparameters
NN_HIDDEN_LAYERS = [128, 128, 64]
NN_LEARNING_RATE = 0.001
NN_EPOCHS = 100

# Lineup optimization
DEFAULT_BUDGET = 500
DEFAULT_FORMATION = '3-4-3'
LINEUP_SIMULATION_ITERATIONS = 10000
```

## 📝 Manual Data Requirements

Some data must be manually downloaded:

1. **Fantacalcio Quotazioni** (from fantacalcio.it)
   - Place in: `data/fantacalcio/Quotazioni_Fantacalcio.xlsx`

2. **Weekly Votes** (from fantacalcio.it)
   - Place in: `data/fantacalcio/voti/Voti_Fantacalcio_Stagione_YYYY_MM_Giornata_XX.xlsx`

3. **Serie A Calendar**
   - Place in: `data/fantacalcio/seriea_calendar.xlsx`

4. **Name Fixes** (optional)
   - Create: `config/name_fix.txt` (CSV format: fbref_name,fantacalcio_name)

## 🧪 Testing

```bash
# Run all tests
pytest tests/

# Run specific test module
pytest tests/test_name_matching.py

# Run with coverage
pytest --cov=src tests/
```

## 📚 Code Quality Improvements

### Before Refactoring
- 9 Jupyter notebooks with ~3000 lines
- 40% code duplication (notebooks 3/3b, 4/4b identical)
- Hard-coded paths throughout
- No error handling
- Manual cell-by-cell execution

### After Refactoring
- Modular Python packages (~2000 lines total)
- <5% duplication
- Centralized configuration
- Comprehensive error handling and logging
- One-command execution
- Unit testable
- Reusable modules

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📄 License

This project builds upon:
- [Scrape-FBref-data](https://github.com/parth1902/Scrape-FBref-data) - FBRef scraping code
- [ff_prob](https://github.com/amiles2233/ff_prob) - Inspiration for Bayesian approach

## 🙏 Credits

- **FBRef.com** - Comprehensive football statistics
- **Fantacalcio.it** - The game and vote data
- **Original Repository** - [fantabeto](https://github.com/[original-repo]) by [original author]

## 📞 Support

For issues, questions, or contributions:
- Open an issue on GitHub
- Check existing documentation
- Review the notebooks for examples

---

## 🎯 Example: Complete Workflow

```python
from config.settings import config
from src.scrapers.fbref_scraper import FBRefScraper
from src.data_processing.votes_processor import VotesProcessor
from src.data_processing.players_processor import PlayersProcessor
from src.data_processing.match_data_builder import MatchDataBuilder
from src.models.neural_network import FantacalcioPredictor
from src.models.lineup_optimizer import LineupOptimizer

# 1. Scrape FBRef data
scraper = FBRefScraper()
fbref_data = scraper.scrape_all(save_dir=config.FBREF_DATA_DIR)

# 2. Process votes
votes_proc = VotesProcessor()
votes_df = votes_proc.process_all_matchdays(max_matchday=20)

# 3. Merge player data
players_proc = PlayersProcessor()
players_df = players_proc.merge_all_sources()

# 4. Build training dataset
builder = MatchDataBuilder()
training_data = builder.build_complete_dataset()

# 5. Train model
predictor = FantacalcioPredictor()
predictor.train(training_data['outfield'], training_data['goalkeepers'])
predictor.save_model(version='2324_v1')

# 6. Generate predictions
predictions = predictor.predict_matchday(matchday=21)

# 7. Optimize lineup
optimizer = LineupOptimizer(predictions, budget=500, formation='3-4-3')
best_lineup = optimizer.get_optimal_lineup()
print(best_lineup)
```

---

**Built with ❤️ for Fantacalcio enthusiasts**
