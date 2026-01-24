#!/bin/zsh
set -e

# Default to fast mode
ARGS=(-m "not slow")

# Check for arguments
if [[ "$1" == "--full" ]]; then
    echo "🐢 Running FULL test suite..."
    ARGS=()
elif [[ "$1" == "--cov" ]]; then
    echo "📊 Running tests with coverage..."
    ARGS=(--cov=custom_components.solax_modbus --cov-report=term-missing)
else
    echo "🐇 Running FAST tests (skipping @slow)..."
fi

# Run pytest via uv
uv run pytest "${ARGS[@]}"
