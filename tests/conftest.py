"""Global fixtures for solax_modbus integration tests."""
import pytest
from pytest_homeassistant_custom_component.common import async_test_home_assistant

@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations defined in the test dir."""
    yield
