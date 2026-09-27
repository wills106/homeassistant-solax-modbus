"""Structural safeguards for computed sensor readiness contracts."""

import ast
from pathlib import Path

INTEGRATION_ROOT = Path(__file__).parents[2] / "custom_components" / "solax_modbus"


def _is_computed_sensor_description(node: ast.Call) -> bool:
    function = node.func
    name = function.id if isinstance(function, ast.Name) else function.attr if isinstance(function, ast.Attribute) else ""
    if not name.endswith("ModbusSensorEntityDescription"):
        return False
    keywords = {keyword.arg: keyword.value for keyword in node.keywords if keyword.arg}
    if "value_function" not in keywords:
        return False
    register = keywords.get("register")
    return not (isinstance(register, ast.Constant) and isinstance(register.value, int) and register.value >= 0)


def test_every_static_computed_sensor_declares_an_input_contract() -> None:
    missing: list[str] = []

    for path in sorted(INTEGRATION_ROOT.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not _is_computed_sensor_description(node):
                continue
            keywords = {keyword.arg: keyword.value for keyword in node.keywords if keyword.arg}
            if "depends_on" not in keywords:
                missing.append(f"{path.name}:{node.lineno}")

    assert not missing, "Computed sensors without an explicit input contract: " + ", ".join(missing)


def test_sensor_platform_does_not_bypass_shared_computed_evaluator() -> None:
    path = INTEGRATION_ROOT / "sensor.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    direct_calls = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "value_function"
    ]

    assert not direct_calls, f"sensor.py calls value_function directly at lines {direct_calls}"
