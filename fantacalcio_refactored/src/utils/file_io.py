"""
File I/O utilities for the Fantacalcio project.

Handles reading and writing CSV, Excel files with consistent error handling.
"""

import pandas as pd
from pathlib import Path
from typing import Optional, Union, List
import logging

logger = logging.getLogger(__name__)


def read_csv_safe(filepath: Union[str, Path], 
                  index_col: Optional[Union[int, str]] = None,
                  **kwargs) -> pd.DataFrame:
    """
    Safely read a CSV file with error handling.
    
    Args:
        filepath: Path to CSV file
        index_col: Column to use as index
        **kwargs: Additional arguments for pd.read_csv
        
    Returns:
        DataFrame
        
    Raises:
        FileNotFoundError: If file doesn't exist
        pd.errors.ParserError: If CSV parsing fails
    """
    filepath = Path(filepath)
    
    if not filepath.exists():
        raise FileNotFoundError(f"CSV file not found: {filepath}")
    
    try:
        df = pd.read_csv(filepath, index_col=index_col, **kwargs)
        logger.info(f"Successfully loaded CSV: {filepath} ({len(df)} rows)")
        return df
    except Exception as e:
        logger.error(f"Error reading CSV {filepath}: {e}")
        raise


def read_excel_safe(filepath: Union[str, Path],
                    sheet_name: Union[str, int] = 0,
                    index_col: Optional[Union[int, str]] = None,
                    **kwargs) -> pd.DataFrame:
    """
    Safely read an Excel file with error handling.
    
    Args:
        filepath: Path to Excel file
        sheet_name: Sheet name or index
        index_col: Column to use as index
        **kwargs: Additional arguments for pd.read_excel
        
    Returns:
        DataFrame
        
    Raises:
        FileNotFoundError: If file doesn't exist
    """
    filepath = Path(filepath)
    
    if not filepath.exists():
        raise FileNotFoundError(f"Excel file not found: {filepath}")
    
    try:
        df = pd.read_excel(filepath, sheet_name=sheet_name, 
                          index_col=index_col, **kwargs)
        logger.info(f"Successfully loaded Excel: {filepath} ({len(df)} rows)")
        return df
    except Exception as e:
        logger.error(f"Error reading Excel {filepath}: {e}")
        raise


def save_csv(df: pd.DataFrame, 
             filepath: Union[str, Path],
             create_dirs: bool = True,
             **kwargs) -> None:
    """
    Save DataFrame to CSV with directory creation.
    
    Args:
        df: DataFrame to save
        filepath: Destination path
        create_dirs: Create parent directories if they don't exist
        **kwargs: Additional arguments for df.to_csv
    """
    filepath = Path(filepath)
    
    if create_dirs:
        filepath.parent.mkdir(parents=True, exist_ok=True)
    
    try:
        df.to_csv(filepath, **kwargs)
        logger.info(f"Saved CSV: {filepath} ({len(df)} rows)")
    except Exception as e:
        logger.error(f"Error saving CSV {filepath}: {e}")
        raise


def save_excel(df: pd.DataFrame,
               filepath: Union[str, Path],
               sheet_name: str = 'Sheet1',
               create_dirs: bool = True,
               **kwargs) -> None:
    """
    Save DataFrame to Excel with directory creation.
    
    Args:
        df: DataFrame to save
        filepath: Destination path
        sheet_name: Sheet name
        create_dirs: Create parent directories if they don't exist
        **kwargs: Additional arguments for df.to_excel
    """
    filepath = Path(filepath)
    
    if create_dirs:
        filepath.parent.mkdir(parents=True, exist_ok=True)
    
    try:
        df.to_excel(filepath, sheet_name=sheet_name, **kwargs)
        logger.info(f"Saved Excel: {filepath} ({len(df)} rows)")
    except Exception as e:
        logger.error(f"Error saving Excel {filepath}: {e}")
        raise


def save_multiple_sheets(dataframes: dict,
                        filepath: Union[str, Path],
                        create_dirs: bool = True) -> None:
    """
    Save multiple DataFrames to different sheets in one Excel file.
    
    Args:
        dataframes: Dictionary mapping sheet names to DataFrames
        filepath: Destination path
        create_dirs: Create parent directories if they don't exist
    """
    filepath = Path(filepath)
    
    if create_dirs:
        filepath.parent.mkdir(parents=True, exist_ok=True)
    
    try:
        with pd.ExcelWriter(filepath, engine='openpyxl') as writer:
            for sheet_name, df in dataframes.items():
                df.to_excel(writer, sheet_name=sheet_name)
        
        logger.info(f"Saved Excel with {len(dataframes)} sheets: {filepath}")
    except Exception as e:
        logger.error(f"Error saving multi-sheet Excel {filepath}: {e}")
        raise


def list_files(directory: Union[str, Path], 
               pattern: str = '*',
               recursive: bool = False) -> List[Path]:
    """
    List files in a directory matching a pattern.
    
    Args:
        directory: Directory to search
        pattern: Glob pattern (e.g., '*.csv')
        recursive: Search recursively
        
    Returns:
        List of matching file paths
    """
    directory = Path(directory)
    
    if not directory.exists():
        logger.warning(f"Directory does not exist: {directory}")
        return []
    
    if recursive:
        files = list(directory.rglob(pattern))
    else:
        files = list(directory.glob(pattern))
    
    return sorted([f for f in files if f.is_file()])


def ensure_directory(directory: Union[str, Path]) -> Path:
    """
    Ensure a directory exists, create if it doesn't.
    
    Args:
        directory: Directory path
        
    Returns:
        Path object
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def file_exists(filepath: Union[str, Path]) -> bool:
    """
    Check if a file exists.
    
    Args:
        filepath: File path to check
        
    Returns:
        True if file exists, False otherwise
    """
    return Path(filepath).exists()


def get_file_age_days(filepath: Union[str, Path]) -> Optional[int]:
    """
    Get age of file in days.
    
    Args:
        filepath: File path
        
    Returns:
        Age in days or None if file doesn't exist
    """
    filepath = Path(filepath)
    
    if not filepath.exists():
        return None
    
    import time
    file_time = filepath.stat().st_mtime
    current_time = time.time()
    age_seconds = current_time - file_time
    age_days = int(age_seconds / (24 * 3600))
    
    return age_days


class DataCache:
    """
    Simple file-based cache for DataFrames.
    """
    
    def __init__(self, cache_dir: Union[str, Path] = '.cache'):
        """
        Initialize cache.
        
        Args:
            cache_dir: Directory for cache files
        """
        self.cache_dir = ensure_directory(cache_dir)
    
    def get(self, key: str, max_age_days: Optional[int] = None) -> Optional[pd.DataFrame]:
        """
        Get DataFrame from cache.
        
        Args:
            key: Cache key (becomes filename)
            max_age_days: Maximum age in days (None = no limit)
            
        Returns:
            Cached DataFrame or None if not found/expired
        """
        cache_file = self.cache_dir / f"{key}.pkl"
        
        if not cache_file.exists():
            return None
        
        if max_age_days is not None:
            age = get_file_age_days(cache_file)
            if age and age > max_age_days:
                logger.info(f"Cache expired: {key} (age: {age} days)")
                return None
        
        try:
            df = pd.read_pickle(cache_file)
            logger.info(f"Loaded from cache: {key}")
            return df
        except Exception as e:
            logger.warning(f"Error reading cache {key}: {e}")
            return None
    
    def set(self, key: str, df: pd.DataFrame) -> None:
        """
        Save DataFrame to cache.
        
        Args:
            key: Cache key
            df: DataFrame to cache
        """
        cache_file = self.cache_dir / f"{key}.pkl"
        
        try:
            df.to_pickle(cache_file)
            logger.info(f"Saved to cache: {key}")
        except Exception as e:
            logger.warning(f"Error saving cache {key}: {e}")
    
    def clear(self, key: Optional[str] = None) -> None:
        """
        Clear cache.
        
        Args:
            key: Specific key to clear (None = clear all)
        """
        if key:
            cache_file = self.cache_dir / f"{key}.pkl"
            if cache_file.exists():
                cache_file.unlink()
                logger.info(f"Cleared cache: {key}")
        else:
            for cache_file in self.cache_dir.glob("*.pkl"):
                cache_file.unlink()
            logger.info("Cleared all cache")


if __name__ == '__main__':
    # Test utilities
    import tempfile
    
    # Create test data
    test_df = pd.DataFrame({
        'player': ['Player A', 'Player B', 'Player C'],
        'goals': [5, 3, 8],
        'assists': [2, 7, 1]
    })
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        
        # Test CSV
        csv_path = tmpdir / 'test.csv'
        save_csv(test_df, csv_path, index=False)
        loaded_csv = read_csv_safe(csv_path)
        assert len(loaded_csv) == 3
        print("✓ CSV save/load works")
        
        # Test Excel
        excel_path = tmpdir / 'test.xlsx'
        save_excel(test_df, excel_path, index=False)
        loaded_excel = read_excel_safe(excel_path)
        assert len(loaded_excel) == 3
        print("✓ Excel save/load works")
        
        # Test cache
        cache = DataCache(tmpdir / 'cache')
        cache.set('test_data', test_df)
        cached_df = cache.get('test_data')
        assert cached_df is not None
        assert len(cached_df) == 3
        print("✓ Cache works")
