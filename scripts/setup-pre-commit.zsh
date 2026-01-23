#!/bin/zsh
set -e

# Check for uv
if ! command -v uv &> /dev/null; then
    echo "Error: uv is not installed. Please install uv first."
    exit 1
fi

echo "Syncing dependencies via uv..."
uv sync

# Check if we are in CI or Docker (simple heuristic, can be improved)
if [[ -n "$CI" ]]; then
    echo "Running in CI environment. Skipping git hook installation."
elif [[ -f /.dockerenv ]]; then
    echo "Running in Docker environment. Installing git hooks..."
    uv run pre-commit install
else
    # Local development
    echo "Local development environment detected."
    if [[ "$1" == "--install-hooks" ]]; then
        echo "Installing git hooks as requested..."
        uv run pre-commit install
    else
        echo "Skipping git hook installation. Run with --install-hooks to install them."
        echo "You can always run 'uv run pre-commit run --all-files' manually."
    fi
fi

echo "Verifying pre-commit installation..."
uv run pre-commit --version
echo "Linting setup complete."
