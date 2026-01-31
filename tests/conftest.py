import pytest


class MockModbusResponse:
    def __init__(self, registers=None, error=False):
        self.registers = registers if registers else []
        self._error = error

    def isError(self):
        return self._error


class MockHub:
    def __init__(self, name="MockHub", modbus_addr=1):
        self.name = name
        self._modbus_addr = modbus_addr
        self.seriesnumber = None
        self._read_side_effects = {}  # Map (unit, address, count) -> MockModbusResponse

    def configure_read(self, unit, address, count, response):
        """Configure a specific response for a read operation."""
        self._read_side_effects[(unit, address, count)] = response

    async def async_read_input_registers(self, unit, address, count):
        """Simulate reading input registers."""
        key = (unit, address, count)
        if key in self._read_side_effects:
            return self._read_side_effects[key]

        # Default empty response if not configured
        return MockModbusResponse(registers=[0] * count)

    async def async_read_holding_registers(self, unit, address, count):
        """Simulate reading holding registers."""
        # For now, treat same as input registers for mocking purposes
        return await self.async_read_input_registers(unit, address, count)


@pytest.fixture
def mock_hub():
    return MockHub()
