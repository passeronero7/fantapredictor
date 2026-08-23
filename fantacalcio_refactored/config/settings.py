"""
Central configuration for Fantacalcio project.

All file paths, URLs, and model hyperparameters are defined here.
"""

import os
from pathlib import Path

# Project root directory
PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / 'data'


class Config:
    """Main configuration class for the Fantacalcio project."""
    
    # ========================
    # DIRECTORY PATHS
    # ========================
    SEASON_DATA_DIR = DATA_DIR / 'season_2026_27'
    FBREF_DATA_DIR = SEASON_DATA_DIR / 'fbref_data'
    FANTACALCIO_DIR = SEASON_DATA_DIR / 'fantacalcio'
    MID_OUTPUTS_DIR = SEASON_DATA_DIR / 'mid_outputs'
    OUTPUTS_DIR = SEASON_DATA_DIR / 'outputs'
    CONFIG_DIR = PROJECT_ROOT / 'config'
    
    # ========================
    # FBREF DATA FILES
    # ========================
    OUTFIELD_PLAYERS_FILE = 'outfield_players.csv'
    KEEPERS_FILE = 'keepers_players.csv'
    TEAMS_FILE = 'teams.csv'
    TEAMS_VS_FILE = 'teams_vs.csv'
    
    # ========================
    # FANTACALCIO FILES
    # ========================
    CALENDAR_FILE = 'seriea_calendar.xlsx'
    QUOTAZIONI_FILE = 'Quotazioni_Fantacalcio.xlsx'
    VOTES_DIR = 'voti'
    
    # ========================
    # MID OUTPUT FILES
    # ========================
    PLAYERS_VOTES_FILE = 'players_votes.xlsx'
    PLAYERS_STATS_FILE = 'players_stats.xlsx'
    PLAYERS_STATS_REWORKED_FILE = 'players_stats_rwk.xlsx'
    TEAM_DATA_FILE = 'team_data.xlsx'
    DATABASE_ENTRIES_FILE = 'database_entries.xlsx'
    DATABASE_ENTRIES_GK_FILE = 'database_entries_gk.xlsx'
    MATCH_PROBABLE_PLAYERS_FILE = 'match_probable_players.xlsx'
    
    # ========================
    # NAME MATCHING CONFIG
    # ========================
    NAME_FIX_FILE = CONFIG_DIR / 'name_fix.txt'
    
    # ========================
    # WEB SCRAPING URLs
    # ========================
    FBREF_SERIE_A_BASE_URL = 'https://fbref.com/en/comps/11/'
    FBREF_SERIE_A_SUFFIX = '/Serie-A-Stats'
    FANTACALCIO_PROBABLE_LINEUPS_URL = 'https://www.fantacalcio.it/probabili-formazioni-serie-a'
    FANTACALCIO_VOTES_BASE_URL = 'https://www.fantacalcio.it/voti-fantacalcio-serie-a'
    
    # ========================
    # SEASON CONFIGURATION
    # ========================
    CURRENT_SEASON = '2627'  # Format: YXYY (e.g., 2627 for 2026/27)
    CURRENT_SEASON_FULL = '2026_27'
    
    # Historical seasons for training
    HISTORICAL_SEASONS = ['2021', '2122', '2223']
    
    # ========================
    # DATA PROCESSING SETTINGS
    # ========================
    # Vote file naming pattern
    VOTES_FILE_PATTERN = 'Voti_Fantacalcio_Stagione_{season}_Giornata_{matchday}.xlsx'
    
    # Serie A calendar
    TOTAL_MATCHDAYS = 38
    MIN_GAMES_FOR_STATS = 6
    
    # ========================
    # FEATURE LISTS
    # ========================
    
    # Standard stats (outfield players)
    OUTFIELD_STATS = [
        "player", "nationality", "position", "team", "age", "birth_year",
        "games", "games_starts", "minutes", "goals", "assists", 
        "pens_made", "pens_att", "cards_yellow", "cards_red",
        "goals_per90", "assists_per90", "goals_assists_per90",
        "goals_pens_per90", "goals_assists_pens_per90",
        "xg", "npxg", "xa", "xg_per90", "xa_per90", "xg_xa_per90",
        "npxg_per90", "npxg_xa_per90"
    ]
    
    # Shooting stats
    SHOOTING_STATS = [
        "player", "nationality", "position", "team", "age", "birth_year",
        "shots_total", "shots_on_target", "shots_on_target_pct",
        "shots_total_per90", "shots_on_target_per90",
        "goals_per_shot", "goals_per_shot_on_target",
        "average_shot_distance", "shots_free_kicks",
        "pens_made", "pens_att"
    ]
    
    # Passing stats
    PASSING_STATS = [
        "player", "nationality", "position", "team", "age", "birth_year",
        "passes_completed", "passes", "passes_pct",
        "passes_total_distance", "passes_progressive_distance",
        "passes_completed_short", "passes_short", "passes_pct_short",
        "passes_completed_medium", "passes_medium", "passes_pct_medium",
        "passes_completed_long", "passes_long", "passes_pct_long",
        "assists", "xa", "assisted_shots", "passes_into_final_third",
        "passes_into_penalty_area", "crosses_into_penalty_area",
        "progressive_passes"
    ]
    
    # Pass types
    PASS_TYPES_STATS = [
        "player", "nationality", "position", "team", "age", "birth_year",
        "passes", "passes_live", "passes_dead", "passes_free_kicks",
        "through_balls", "passes_pressure", "passes_switches",
        "crosses", "corner_kicks", "corner_kicks_in", "corner_kicks_out",
        "corner_kicks_straight", "passes_ground", "passes_low",
        "passes_high", "passes_left_foot", "passes_right_foot",
        "passes_head", "throw_ins", "passes_other_body",
        "passes_completed", "passes_offsides", "passes_oob",
        "passes_intercepted", "passes_blocked"
    ]
    
    # Goal and shot creation
    GCA_STATS = [
        "player", "nationality", "position", "team", "age", "birth_year",
        "sca", "sca_per90", "sca_passes_live", "sca_passes_dead",
        "sca_dribbles", "sca_shots", "sca_fouled", "sca_defense",
        "gca", "gca_per90", "gca_passes_live", "gca_passes_dead",
        "gca_dribbles", "gca_shots", "gca_fouled", "gca_defense"
    ]
    
    # Defensive actions
    DEFENSE_STATS = [
        "player", "nationality", "position", "team", "age", "birth_year",
        "tackles", "tackles_won", "tackles_def_3rd", "tackles_mid_3rd",
        "tackles_att_3rd", "dribble_tackles", "dribbles_vs",
        "dribble_tackles_pct", "dribbled_past", "pressures",
        "pressure_regains", "pressure_regain_pct", "pressures_def_3rd",
        "pressures_mid_3rd", "pressures_att_3rd", "blocks",
        "blocked_shots", "blocked_shots_saves", "blocked_passes",
        "interceptions", "tackles_interceptions", "clearances",
        "errors"
    ]
    
    # Possession
    POSSESSION_STATS = [
        "player", "nationality", "position", "team", "age", "birth_year",
        "touches", "touches_def_pen_area", "touches_def_3rd",
        "touches_mid_3rd", "touches_att_3rd", "touches_att_pen_area",
        "touches_live_ball", "dribbles_completed", "dribbles",
        "dribbles_completed_pct", "players_dribbled_past",
        "nutmegs", "carries", "carry_distance",
        "carry_progressive_distance", "progressive_carries",
        "carries_into_final_third", "carries_into_penalty_area",
        "miscontrols", "dispossessed", "pass_targets",
        "passes_received", "passes_received_pct",
        "progressive_passes_received"
    ]
    
    # Playing time
    PLAYING_TIME_STATS = [
        "player", "nationality", "position", "team", "age", "birth_year",
        "games", "minutes", "minutes_per_game", "minutes_pct",
        "minutes_90s", "games_starts", "minutes_per_start",
        "games_complete", "games_subs", "minutes_per_sub",
        "unused_sub", "points_per_game", "on_goals_for",
        "on_goals_against", "plus_minus", "plus_minus_per90",
        "plus_minus_wowy", "on_xg_for", "on_xg_against",
        "xg_plus_minus", "xg_plus_minus_per90", "xg_plus_minus_wowy"
    ]
    
    # Miscellaneous stats
    MISC_STATS = [
        "player", "nationality", "position", "team", "age", "birth_year",
        "cards_yellow", "cards_red", "cards_yellow_red", "fouls",
        "fouled", "offsides", "crosses", "interceptions",
        "tackles_won", "pens_won", "pens_conceded", "own_goals",
        "ball_recoveries", "aerials_won", "aerials_lost",
        "aerials_won_pct"
    ]
    
    # Goalkeeper stats
    GK_STATS = [
        "player", "nationality", "position", "team", "age", "birth_year",
        "games", "games_starts", "minutes", "minutes_90s",
        "goals_against", "goals_against_per90", "shots_on_target_against",
        "saves", "save_pct", "wins", "draws", "losses",
        "clean_sheets", "clean_sheets_pct", "pens_att", "pens_allowed",
        "pens_saved", "pens_missed", "pens_save_pct"
    ]
    
    # Advanced GK stats
    GK_ADV_STATS = [
        "player", "nationality", "position", "team", "age", "birth_year",
        "goals_against", "pens_allowed", "free_kick_goals_against",
        "corner_kick_goals_against", "own_goals_against",
        "psxg", "psxg_per_shot_on_target", "psxg_net", "psxg_net_per90",
        "passes_completed_launched", "passes_launched",
        "passes_pct_launched", "passes", "passes_throws",
        "passes_launch_pct", "passes_avg_len",
        "goal_kicks", "goal_kick_pct_launched",
        "goal_kick_avg_len", "crosses_against", "crosses_stopped",
        "crosses_stopped_pct", "def_actions_outside_pen_area",
        "def_actions_outside_pen_area_per90",
        "avg_distance_def_actions"
    ]
    
    # Team stats categories
    TEAM_STATS_CATEGORIES = [
        'standard', 'keeper', 'advanced_keeper', 'shooting',
        'passing', 'pass_types', 'goal_shot_creation',
        'defense', 'possession', 'playing_time', 'misc'
    ]
    
    # ========================
    # FEATURES TO DELETE (OPTIONAL)
    # ========================
    FEATURES_TO_DELETE = [
        'goals',
        'assists',
        'xg',
        'npxg'
    ]
    
    # ========================
    # MODEL HYPERPARAMETERS
    # ========================
    
    # Neural network architecture
    NN_HIDDEN_LAYERS = [128, 128, 64]
    NN_DROPOUT_RATE = 0.2
    NN_LEARNING_RATE = 0.001
    NN_BATCH_SIZE = 32
    NN_EPOCHS = 100
    NN_VALIDATION_SPLIT = 0.2
    NN_EARLY_STOPPING_PATIENCE = 15
    
    # Output distribution parameters
    # For outfield players: [loc, scale, skewness, tailweight] for vote and fantavote
    NN_OUTPUT_PARAMS_OUTFIELD = 8  # 4 params for vote + 4 for fantavote
    # For goalkeepers: [loc, scale, skewness, tailweight] for vote + 1 for clean sheet probability
    NN_OUTPUT_PARAMS_GK = 5
    
    # Training data weights
    WEIGHT_SAME_TEAM = 0.7  # Weight for current season stats (same team)
    WEIGHT_DIFFERENT_TEAM = 0.4  # Weight for current season stats (different team)
    WEIGHT_HISTORICAL = 0.3  # Weight for historical season stats
    
    # Season stats adaptation
    MIN_CURRENT_SEASON_GAMES = 6
    MAX_CURRENT_SEASON_GAMES = 30
    SEASON_WEIGHT_MATCHDAY_THRESHOLD = 12
    
    # ========================
    # LINEUP OPTIMIZATION
    # ========================
    
    # Fantasy football constraints
    DEFAULT_BUDGET = 500  # Credits
    DEFAULT_FORMATION = '3-4-3'  # Defenders-Midfielders-Forwards
    
    # Simulation parameters
    LINEUP_SIMULATION_ITERATIONS = 10000
    
    # Modificatore (defense modifier) bonuses
    MODIFICATORE_THRESHOLDS = [
        (0, 3),    # 3 points if 0 goals conceded
        (1, 1),    # 1 point if 1 goal conceded
        (2, 0),    # 0 points if 2+ goals conceded
    ]
    
    # Clean sheet bonus
    CLEAN_SHEET_BONUS = 1
    
    # ========================
    # LOGGING CONFIGURATION
    # ========================
    LOG_LEVEL = 'INFO'
    LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    LOG_FILE = PROJECT_ROOT / 'fantacalcio.log'
    
    # ========================
    # UTILITY METHODS
    # ========================
    
    @classmethod
    def get_season_dir(cls, season: str = None) -> Path:
        """Return the canonical data directory for a compact season code."""
        season = season or cls.CURRENT_SEASON
        if len(season) == 4 and season.isdigit():
            season = f'20{season[:2]}_{season[2:]}'
        return DATA_DIR / f'season_{season}'

    @classmethod
    def get_fbref_base_url(cls, season: str = None) -> str:
        """Return the FBref competition URL for the requested season."""
        season_dir = cls.get_season_dir(season).name.removeprefix('season_')
        return f'{cls.FBREF_SERIE_A_BASE_URL}{season_dir.replace("_", "-")}/'

    @classmethod
    def get_fbref_path(cls, filename: str, season: str = None) -> Path:
        """Get path for FBref data file."""
        return cls.get_season_dir(season) / 'fbref_data' / filename
    
    @classmethod
    def get_mid_output_path(cls, filename: str, season: str = None) -> Path:
        """Get path for intermediate output file."""
        return cls.get_season_dir(season) / 'mid_outputs' / filename
    
    @classmethod
    def get_votes_file_path(cls, season: str, matchday: int) -> Path:
        """Get path for votes file."""
        filename = cls.VOTES_FILE_PATTERN.format(
            season=season.replace('_', '_'),
            matchday=matchday
        )
        return cls.get_season_dir(season) / 'fantacalcio' / cls.VOTES_DIR / filename
    
    @classmethod
    def ensure_directories(cls):
        """Create all necessary directories if they don't exist."""
        directories = [
            cls.FBREF_DATA_DIR,
            cls.FANTACALCIO_DIR,
            cls.MID_OUTPUTS_DIR,
            cls.OUTPUTS_DIR,
            cls.FANTACALCIO_DIR / cls.VOTES_DIR,
        ]
        
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)
        
        # Historical directories are created only when their data is requested.


# Create singleton instance
config = Config()
