#!/bin/zsh
set -e

# Check for uv
if ! command -v uv &> /dev/null; then
    echo "Error: uv is not installed. Please install uv first."
    exit 1
fi

echo "Syncing dependencies via uv..."
uv sync

# Check if we are in GitHub Actions CI
if [[ -n "$GITHUB_ACTIONS" ]]; then
    echo "Running in CI environment. Skipping git hook installation."
else
    # Local development or Docker
    echo "Installing git hooks..."
    uv run pre-commit install
fi

echo "Verifying pre-commit installation..."
uv run pre-commit --version
echo "Linting setup complete."
