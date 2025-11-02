#!/bin/bash
# Manual linting script - run checks without committing
# Scope: __init__.py and plugin_solax.py only (Phase 2)

set -e

echo "🔍 Linting SolaX Modbus Integration (Phase 2 scope)"
echo "=============================================="
echo ""

SCOPE="custom_components/solax_modbus/__init__.py custom_components/solax_modbus/plugin_solax.py"

echo "📁 Scope: __init__.py and plugin_solax.py"
echo ""

echo "🔍 Running Black (check only)..."
if command -v black &>/dev/null; then
    black --check --diff $SCOPE
    echo "✅ Black check complete"
else
    echo "⚠️  Black not installed (pip install black)"
fi

echo ""
echo "🔍 Running Flake8..."
if command -v flake8 &>/dev/null; then
    flake8 $SCOPE
    echo "✅ Flake8 check complete"
else
    echo "⚠️  Flake8 not installed (pip install flake8)"
fi

echo ""
echo "🔍 Running codespell..."
if command -v codespell &>/dev/null; then
    codespell $SCOPE
    echo "✅ Codespell check complete"
else
    echo "⚠️  Codespell not installed (pip install codespell)"
fi

echo ""
echo "✅ All linting checks complete!"
echo ""
echo "💡 To auto-fix formatting: ./scripts/format.sh"

