"""
Utility functions for matching player names between different data sources.

Handles accent normalization, special characters, and name variations.
"""

import re
import unicodedata
from typing import Dict, Optional
import pandas as pd
from pathlib import Path


def normalize_name(name: str) -> str:
    """
    Normalize a player name by removing accents and special characters.
    
    Args:
        name: Original player name
        
    Returns:
        Normalized name (lowercase, no accents, only alphanumeric + spaces)
    """
    if not isinstance(name, str):
        return ""
    
    # Convert to lowercase
    name = name.lower()
    
    # Remove accents
    name = unicodedata.normalize('NFD', name)
    name = ''.join(char for char in name if unicodedata.category(char) != 'Mn')
    
    # Remove special characters (keep only letters, numbers, spaces, hyphens)
    name = re.sub(r'[^a-z0-9\s\-]', '', name)
    
    # Remove extra whitespace
    name = ' '.join(name.split())
    
    return name


def extract_surname(full_name: str) -> str:
    """
    Extract surname from full name (typically the last word).
    
    Args:
        full_name: Full player name
        
    Returns:
        Surname
    """
    if not isinstance(full_name, str):
        return ""
    
    parts = full_name.strip().split()
    if not parts:
        return ""
    
    # Return last word as surname
    return parts[-1]


def extract_surname_normalized(full_name: str) -> str:
    """
    Extract and normalize surname.
    
    Args:
        full_name: Full player name
        
    Returns:
        Normalized surname
    """
    surname = extract_surname(full_name)
    return normalize_name(surname)


class NameMatcher:
    """
    Class for matching player names between different data sources.
    
    Handles manual fixes and fuzzy matching.
    """
    
    def __init__(self, name_fix_file: Optional[Path] = None):
        """
        Initialize name matcher.
        
        Args:
            name_fix_file: Path to CSV file with manual name mappings
        """
        self.manual_fixes = {}
        
        if name_fix_file and name_fix_file.exists():
            self.load_manual_fixes(name_fix_file)
    
    def load_manual_fixes(self, filepath: Path):
        """
        Load manual name fixes from file.
        
        Expected format: CSV with columns [fbref_name, fantacalcio_name]
        
        Args:
            filepath: Path to name fix file
        """
        try:
            df = pd.read_csv(filepath, header=None, names=['fbref', 'fantacalcio'])
            self.manual_fixes = dict(zip(df['fbref'], df['fantacalcio']))
        except Exception as e:
            print(f"Warning: Could not load name fixes from {filepath}: {e}")
    
    def match_name(self, name: str, use_manual: bool = True) -> str:
        """
        Match and normalize a player name.
        
        Args:
            name: Original player name
            use_manual: Whether to apply manual fixes
            
        Returns:
            Matched/normalized name
        """
        if use_manual and name in self.manual_fixes:
            return self.manual_fixes[name]
        
        return normalize_name(name)
    
    def add_manual_fix(self, original: str, fixed: str):
        """
        Add a manual name fix.
        
        Args:
            original: Original name
            fixed: Corrected name
        """
        self.manual_fixes[original] = fixed
    
    def save_manual_fixes(self, filepath: Path):
        """
        Save manual fixes to file.
        
        Args:
            filepath: Path to save name fixes
        """
        df = pd.DataFrame(list(self.manual_fixes.items()), 
                         columns=['fbref', 'fantacalcio'])
        df.to_csv(filepath, index=False, header=False)


def create_player_lookup(df: pd.DataFrame, 
                         name_col: str = 'player',
                         team_col: str = 'team') -> Dict[tuple, int]:
    """
    Create a lookup dictionary for players based on name and team.
    
    Args:
        df: DataFrame with player data
        name_col: Column name for player names
        team_col: Column name for team names
        
    Returns:
        Dictionary mapping (normalized_name, team) to dataframe index
    """
    lookup = {}
    
    for idx, row in df.iterrows():
        name = normalize_name(row[name_col])
        team = row[team_col] if team_col in row else None
        
        key = (name, team) if team else (name,)
        lookup[key] = idx
    
    return lookup


def fuzzy_match_name(target: str, 
                    candidates: list, 
                    threshold: float = 0.8) -> Optional[str]:
    """
    Find best fuzzy match for a name from a list of candidates.
    
    Args:
        target: Name to match
        candidates: List of candidate names
        threshold: Minimum similarity score (0-1)
        
    Returns:
        Best matching candidate or None
    """
    from difflib import SequenceMatcher
    
    target_norm = normalize_name(target)
    best_match = None
    best_score = 0
    
    for candidate in candidates:
        candidate_norm = normalize_name(candidate)
        score = SequenceMatcher(None, target_norm, candidate_norm).ratio()
        
        if score > best_score and score >= threshold:
            best_score = score
            best_match = candidate
    
    return best_match


# Predefined special cases for Serie A teams
TEAM_NAME_MAPPINGS = {
    # FBref -> Fantacalcio
    'Inter Milan': 'Inter',
    'AC Milan': 'Milan',
    'AS Roma': 'Roma',
    'Hellas Verona': 'Verona',
    'Atalanta': 'Atalanta',
    'Bologna': 'Bologna',
    'Cagliari': 'Cagliari',
    'Empoli': 'Empoli',
    'Fiorentina': 'Fiorentina',
    'Frosinone': 'Frosinone',
    'Genoa': 'Genoa',
    'Juventus': 'Juventus',
    'Lazio': 'Lazio',
    'Lecce': 'Lecce',
    'Monza': 'Monza',
    'Napoli': 'Napoli',
    'Salernitana': 'Salernitana',
    'Sassuolo': 'Sassuolo',
    'Torino': 'Torino',
    'Udinese': 'Udinese',
}


def normalize_team_name(team_name: str) -> str:
    """
    Normalize team name for matching between sources.
    
    Args:
        team_name: Original team name
        
    Returns:
        Normalized team name
    """
    if team_name in TEAM_NAME_MAPPINGS:
        return TEAM_NAME_MAPPINGS[team_name]
    
    return team_name


if __name__ == '__main__':
    # Test the utilities
    test_names = [
        "Rafael Leão",
        "Khvicha Kvaratskhelia",
        "Victor Osimhen",
        "Dušan Vlahović"
    ]
    
    print("Name normalization tests:")
    for name in test_names:
        print(f"{name:30} -> {normalize_name(name)}")
    
    print("\nSurname extraction tests:")
    for name in test_names:
        print(f"{name:30} -> {extract_surname_normalized(name)}")
