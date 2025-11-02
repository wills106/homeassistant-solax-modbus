#!/bin/bash
# Auto-fix formatting issues
# Scope: __init__.py and plugin_solax.py only (Phase 2)

set -e

echo "🔧 Auto-formatting SolaX Modbus Integration (Phase 2 scope)"
echo "========================================================="
echo ""

SCOPE="custom_components/solax_modbus/__init__.py custom_components/solax_modbus/plugin_solax.py"

echo "📁 Scope: __init__.py and plugin_solax.py"
echo ""

echo "🔧 Running Black (auto-fix)..."
if command -v black &>/dev/null; then
    black $SCOPE
    echo "✅ Black formatting complete"
else
    echo "⚠️  Black not installed (pip install black)"
fi

echo ""
echo "🔧 Running codespell (auto-fix)..."
if command -v codespell &>/dev/null; then
    codespell --write-changes $SCOPE
    echo "✅ Codespell fixes complete"
else
    echo "⚠️  Codespell not installed (pip install codespell)"
fi

echo ""
echo "✅ Auto-formatting complete!"
echo "💡 Run ./scripts/lint.sh to verify"

