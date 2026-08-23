#!/bin/bash
# Setup script for Fantacalcio refactored codebase

set -e

echo "========================================"
echo "Fantacalcio Setup Script"
echo "========================================"
echo ""

# Configuration
SOURCE_DIR="/home/claude/fantacalcio_refactored"
TARGET_DIR="/home/mep/Documents/fantacalcio"

echo "Source: $SOURCE_DIR"
echo "Target: $TARGET_DIR"
echo ""

# Check if source exists
if [ ! -d "$SOURCE_DIR" ]; then
    echo "ERROR: Source directory not found: $SOURCE_DIR"
    exit 1
fi

# Create target directory
echo "Creating target directory..."
mkdir -p "$TARGET_DIR"

# Copy files
echo "Copying refactored codebase..."
if command -v rsync &> /dev/null; then
    # Use rsync if available (better for incremental updates)
    rsync -av --progress "$SOURCE_DIR/" "$TARGET_DIR/"
else
    # Fallback to cp
    cp -r "$SOURCE_DIR"/* "$TARGET_DIR"/
fi

echo ""
echo "✓ Files copied successfully!"
echo ""

# Create Python virtual environment (optional)
read -p "Create Python virtual environment? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    cd "$TARGET_DIR"
    echo "Creating virtual environment..."
    python3 -m venv venv
    echo "✓ Virtual environment created"
    echo ""
    echo "To activate:"
    echo "  cd $TARGET_DIR"
    echo "  source venv/bin/activate"
    echo "  pip install -r requirements.txt"
fi

echo ""
echo "========================================"
echo "Setup Complete!"
echo "========================================"
echo ""
echo "Next steps:"
echo "1. cd $TARGET_DIR"
echo "2. source venv/bin/activate  # if you created venv"
echo "3. pip install -r requirements.txt"
echo "4. Read MIGRATION_GUIDE.md for implementation roadmap"
echo "5. Run: python scripts/run_pipeline.py --help"
echo ""
echo "Project structure:"
echo "  config/        - Configuration files"
echo "  src/           - Source code modules"
echo "  scripts/       - Executable scripts"
echo "  data/          - Data directories"
echo "  notebooks/     - Jupyter notebooks (optional)"
echo "  tests/         - Unit tests"
echo ""
echo "Happy coding! 🚀"
