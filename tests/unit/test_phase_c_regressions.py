"""Phase C regression tests - prevent reintroduction of linting errors."""

import ast
import re
from pathlib import Path

import pytest


def get_plugin_files():
    """Get all Python plugin files."""
    plugin_dir = Path("custom_components/solax_modbus")
    return list(plugin_dir.glob("plugin_*.py"))


def get_all_python_files():
    """Get all Python files in the integration."""
    source_dir = Path("custom_components/solax_modbus")
    return [f for f in source_dir.glob("*.py") if f.name != "__pycache__"]


class TestF821UndefinedNames:
    """Test that all referenced names are defined or imported."""

    def test_no_undefined_sensor_types_mic(self):
        """SENSOR_TYPES_MIC must not be referenced (was never defined)."""
        plugin_files = get_plugin_files()
        violations = []

        for plugin_file in plugin_files:
            content = plugin_file.read_text()
            if "SENSOR_TYPES_MIC" in content:
                violations.append(str(plugin_file))

        assert not violations, f"Files still reference undefined SENSOR_TYPES_MIC: {violations}"

    def test_required_imports_present(self):
        """Critical imports must be present where used."""
        test_cases = [
            ("plugin_sofar.py", "datetime", "from datetime import datetime"),
            ("plugin_sofar_old.py", "re", "import re"),
            ("plugin_srne.py", "autorepeat_stop", "autorepeat_stop"),
            ("plugin_srne.py", "autorepeat_remaining", "autorepeat_remaining"),
        ]

        for filename, symbol, import_stmt in test_cases:
            file_path = Path(f"custom_components/solax_modbus/{filename}")
            if not file_path.exists():
                continue

            content = file_path.read_text()

            # Check if symbol is used
            if symbol in content:
                assert import_stmt in content, f"{filename} uses {symbol} but missing import: {import_stmt}"


class TestF811RedefinedImports:
    """Test that _LOGGER is not imported and redefined."""

    def test_no_duplicate_logger(self):
        """_LOGGER should not be imported from const and redefined."""
        plugin_files = get_plugin_files()
        violations = []

        for plugin_file in plugin_files:
            content = plugin_file.read_text()

            # Check if _LOGGER is imported from const
            imports_logger_from_const = "_LOGGER" in content and "from custom_components.solax_modbus.const import" in content

            if imports_logger_from_const:
                # Parse AST to find import
                tree = ast.parse(content, filename=str(plugin_file))
                for node in ast.walk(tree):
                    if isinstance(node, ast.ImportFrom):
                        if node.module and "const" in node.module:
                            for alias in node.names:
                                if alias.name == "_LOGGER":
                                    violations.append(str(plugin_file))
                                    break

        assert not violations, f"Files import _LOGGER from const (should only define locally): {violations}"


class TestE722BareExcept:
    """Test that no bare except clauses exist."""

    @pytest.mark.parametrize("python_file", get_all_python_files())
    def test_no_bare_except(self, python_file):
        """No file should contain 'except:' without exception type (unless noqa)."""
        content = python_file.read_text()

        # Look for bare except patterns without noqa comment
        matches = []
        for line_num, line in enumerate(content.splitlines(), 1):
            if re.match(r"^\s+except:\s*$", line):  # Bare except without noqa
                matches.append(f"Line {line_num}: {line.strip()}")

        assert not matches, f"{python_file} contains bare except clauses without noqa:\n" + "\n".join(matches)


class TestE711NoneComparisons:
    """Test that None comparisons use 'is' or 'is not'."""

    @pytest.mark.parametrize("python_file", get_all_python_files())
    def test_no_equality_none_comparisons(self, python_file):
        """No file should use == None or != None."""
        content = python_file.read_text()

        # Look for == None or != None patterns (but skip comments and strings)
        violations = []
        for line_num, line in enumerate(content.splitlines(), 1):
            # Skip comments
            if line.strip().startswith("#"):
                continue

            # Check for bad patterns (not in strings)
            if re.search(r"[^=!](!= *None|== *None)[^=]", line):
                violations.append(f"Line {line_num}: {line.strip()}")

        assert not violations, f"{python_file} contains == None or != None comparisons:\n" + "\n".join(violations)


class TestE741AmbiguousNames:
    """Test that no ambiguous variable names are used."""

    @pytest.mark.parametrize("python_file", get_all_python_files())
    def test_no_single_letter_l(self, python_file):
        """No file should use 'l' as a variable name (ambiguous with 1)."""
        content = python_file.read_text()
        tree = ast.parse(content, filename=str(python_file))

        violations = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id == "l":
                if isinstance(node.ctx, ast.Store):
                    violations.append(f"Line {node.lineno}: variable 'l' assigned")

        assert not violations, f"{python_file} uses ambiguous variable 'l':\n" + "\n".join(violations)


class TestE402ImportLocation:
    """Test that late imports have proper noqa comments."""

    def test_late_imports_documented(self):
        """Files with intentional late imports must have noqa: E402."""
        known_late_import_files = [
            "custom_components/solax_modbus/__init__.py",
            "custom_components/solax_modbus/plugin_solax.py",
            "custom_components/solax_modbus/plugin_solinteg.py",
            "custom_components/solax_modbus/plugin_solis.py",
            "custom_components/solax_modbus/plugin_solis_fb00.py",
        ]

        for file_path in known_late_import_files:
            path = Path(file_path)
            if not path.exists():
                continue

            content = path.read_text()

            # These files should have late imports with noqa comments
            if "# noqa: E402" not in content:
                pytest.fail(f"{file_path} has late imports but no noqa: E402 comment")
