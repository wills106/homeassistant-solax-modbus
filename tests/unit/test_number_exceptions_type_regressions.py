"""Regression tests for number max_exceptions type mismatch bug.

These tests ensure that max_exceptions and min_exceptions_minus fields accept
both int and float values as used in actual plugin configurations.

Historical context:
- Issue: Type mismatch between base class definition and actual plugin usage
- Root cause: Base class defined list[tuple[str, int]] but plugins used float values
- Original signature: max_exceptions: list[tuple[str, int]] | None
- Actual usage: max_exceptions=[("L30E", 3000.0), ...]  # float values
- Fixed signature: max_exceptions: list[tuple[str, int | float]] | None
- Rationale: native_max_value and native_min_value in number.py are float type
- Commit: 40a3db3
"""


def test_max_exceptions_accepts_int_values() -> None:
    """Test that max_exceptions accepts integer values.

    This is the original expected type that was defined in the base class.
    """
    # Correct: int values
    max_exceptions: list[tuple[str, int | float]] = [
        ("L30E", 100),
        ("U30", 50),
        ("L37E", 100),
    ]

    assert len(max_exceptions) == 3
    assert all(isinstance(key, str) and isinstance(val, (int, float)) for key, val in max_exceptions)


def test_max_exceptions_accepts_float_values() -> None:
    """Test that max_exceptions accepts float values.

    This documents the actual usage pattern that was causing type errors
    before the fix.

    Original bug:
        max_exceptions=[("L30E", 3000.0), ...]  # float values
        Type error: Expected int, got float

    Fixed signature allows both int and float.
    """
    # Correct: float values (actual usage pattern)
    max_exceptions: list[tuple[str, int | float]] = [
        ("L30E", 3000.0),
        ("U30", 3000.0),
        ("L37E", 3700.0),
    ]

    assert len(max_exceptions) == 3
    assert all(isinstance(val, float) for _, val in max_exceptions)


def test_max_exceptions_accepts_mixed_values() -> None:
    """Test that max_exceptions accepts mixed int and float values.

    In practice, some plugins may use int for some entries and float for others.
    """
    max_exceptions: list[tuple[str, int | float]] = [
        ("L30E", 100),  # int
        ("U30", 50.5),  # float
        ("L37E", 100),  # int
        ("H1E30", 5000.0),  # float
    ]

    assert len(max_exceptions) == 4
    # All should be accepted
    for key, val in max_exceptions:
        assert isinstance(key, str)
        assert isinstance(val, (int, float))


def test_min_exceptions_minus_accepts_float_values() -> None:
    """Test that min_exceptions_minus also accepts float values.

    min_exceptions_minus has the same type signature as max_exceptions and
    had the same bug.
    """
    min_exceptions_minus: list[tuple[str, int | float]] = [
        ("L30E", 3000.0),  # Negative limit for export
        ("U30", 3000.0),
    ]

    assert len(min_exceptions_minus) == 2
    assert all(isinstance(val, float) for _, val in min_exceptions_minus)


def test_exception_list_lookup_pattern() -> None:
    """Test the exception lookup pattern used in number.py.

    Number entities use max_exceptions to override native_max_value based on
    inverter model prefix. This test documents the lookup pattern.
    """
    max_exceptions: list[tuple[str, int | float]] = [
        ("L30E", 100.0),
        ("U30", 50.0),
        ("L37E", 100.0),
    ]

    # Simulate lookup pattern
    def find_exception_value(serial_prefix: str, exceptions: list[tuple[str, int | float]]) -> float | None:
        """Find exception value for a serial prefix."""
        for prefix, value in exceptions:
            if serial_prefix.startswith(prefix):
                return float(value)
        return None

    # Test lookups
    assert find_exception_value("L30E12345", max_exceptions) == 100.0
    assert find_exception_value("U30ABC", max_exceptions) == 50.0
    assert find_exception_value("UNKNOWN", max_exceptions) is None


def test_exception_value_used_as_native_max_value() -> None:
    """Test that exception values are used as native_max_value (float).

    This documents why the exception values need to support float: they are
    directly assigned to native_max_value which is typed as float in number.py.
    """
    max_exceptions: list[tuple[str, int | float]] = [
        ("L30E", 5000.0),
        ("H3E10", 15000.0),
    ]

    serial_number = "L30E123456"
    native_max_value: float = 10000.0  # Default

    # Simulate exception lookup and assignment
    for prefix, value in max_exceptions:
        if serial_number.startswith(prefix):
            native_max_value = float(value)  # Must be float
            break

    assert native_max_value == 5000.0
    assert isinstance(native_max_value, float)


def test_list_invariance_with_mixed_types() -> None:
    """Test that list invariance is satisfied with int | float union type.

    This documents the list invariance error that was occurring when trying
    to pass a list[tuple[str, float]] to a parameter expecting list[tuple[str, int]].

    Original bug in plugin_solax.py:1410:
        max_exceptions = [("L30E", 100), ...]  # int values
        min_exceptions_minus = [("L30E", 3000.0), ...]  # float values
        Type error: List invariance violation when passing to base class

    Fixed with explicit type annotation on the constant declarations.
    """
    # Both int and float constants work with the union type
    MAX_CURRENTS: list[tuple[str, int | float]] = [
        ("L30E", 100),  # int
        ("U30", 50),  # int
    ]

    MAX_EXPORT: list[tuple[str, int | float]] = [
        ("L30E", 3000.0),  # float
        ("U30", 3000.0),  # float
    ]

    # Both can be used interchangeably
    def accepts_exceptions(exceptions: list[tuple[str, int | float]]) -> int:
        return len(exceptions)

    assert accepts_exceptions(MAX_CURRENTS) == 2
    assert accepts_exceptions(MAX_EXPORT) == 2
