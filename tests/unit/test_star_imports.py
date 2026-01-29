"""Test that star imports are eliminated and won't return.

This test suite ensures that the F405 error resolution work stays resolved
by preventing star imports from being reintroduced to the codebase.
"""

import ast
from pathlib import Path

import pytest


def get_all_python_files():
    """Get all Python files in the custom component."""
    component_dir = Path(__file__).parent.parent.parent / "custom_components" / "solax_modbus"
    return sorted(component_dir.glob("*.py"))


def check_star_imports(filepath):
    """Check if a file contains any star imports."""
    with open(filepath) as f:
        tree = ast.parse(f.read(), filepath)

    star_imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == "*":
                    star_imports.append(
                        {
                            "module": node.module,
                            "line": node.lineno,
                        }
                    )

    return star_imports


@pytest.mark.parametrize("python_file", get_all_python_files())
def test_no_star_imports(python_file):
    """Test that no Python files use star imports.

    Phase B eliminated all star imports to resolve 8,396 F405 errors.
    This test ensures they don't get reintroduced.

    Star imports make it impossible to:
    - Know what symbols are available
    - Use import sorting reliably
    - Detect unused imports
    - See dependencies clearly in code
    """
    star_imports = check_star_imports(python_file)

    assert len(star_imports) == 0, (
        f"{python_file.name} contains star imports that should be explicit:\n"
        + "\n".join(f"  Line {si['line']}: from {si['module']} import *" for si in star_imports)
        + "\n\nConvert to explicit imports listing only the symbols you need."
    )


def test_const_module_not_star_imported():
    """Specific test for const.py star imports.

    The const.py star imports were the primary cause of F405 errors.
    This test specifically ensures they stay eliminated.
    """
    plugin_files = Path(__file__).parent.parent.parent / "custom_components" / "solax_modbus"
    plugin_files = sorted(plugin_files.glob("plugin_*.py"))

    files_with_const_star = []

    for plugin_file in plugin_files:
        with open(plugin_file) as f:
            tree = ast.parse(f.read(), plugin_file)

        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if "const" in (node.module or ""):
                    for alias in node.names:
                        if alias.name == "*":
                            files_with_const_star.append(plugin_file.name)

    assert len(files_with_const_star) == 0, (
        "These files have 'from const import *' which causes F405 errors:\n"
        + "\n".join(f"  - {f}" for f in files_with_const_star)
        + f"\n\nPhase B eliminated all {len(plugin_files)} plugin file star imports. "
        "They must not be reintroduced."
    )


def test_star_import_documentation():
    """Document that star imports were eliminated in Phase B.

    This test serves as documentation and will fail if the count changes,
    prompting investigation.
    """
    all_files = get_all_python_files()

    # Count total star imports across all files
    total_star_imports = 0
    for python_file in all_files:
        total_star_imports += len(check_star_imports(python_file))

    # Phase B should have eliminated ALL star imports
    assert total_star_imports == 0, (
        f"Expected 0 star imports after Phase B, found {total_star_imports}. Phase B work may have been reverted or new star imports added."
    )

    # Document the scope of Phase B work
    plugin_files = [f for f in all_files if f.name.startswith("plugin_")]
    assert len(plugin_files) == 17, (
        f"Expected 17 plugin files, found {len(plugin_files)}. If plugin files were added, ensure they don't use star imports."
    )
