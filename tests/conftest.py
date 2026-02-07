import pytest


class MockModbusResponse:
    def __init__(self, registers: list[int] | None = None, error: bool = False) -> None:
        self.registers = registers if registers else []
        self._error = error

    def isError(self) -> bool:
        return self._error


class MockHub:
    def __init__(self, name: str = "MockHub", modbus_addr: int = 1) -> None:
        self.name = name
        self._modbus_addr = modbus_addr
        self.seriesnumber: str | None = None
        self._read_side_effects: dict[tuple[int, int, int], MockModbusResponse] = {}  # Map (unit, address, count) -> MockModbusResponse

    def configure_read(self, unit: int, address: int, count: int, response: MockModbusResponse) -> None:
        """Configure a specific response for a read operation."""
        self._read_side_effects[(unit, address, count)] = response

    async def async_read_input_registers(self, unit: int, address: int, count: int) -> MockModbusResponse:
        """Simulate reading input registers."""
        key = (unit, address, count)
        if key in self._read_side_effects:
            return self._read_side_effects[key]

        # Default empty response if not configured
        return MockModbusResponse(registers=[0] * count)

    async def async_read_holding_registers(self, unit: int, address: int, count: int) -> MockModbusResponse:
        """Simulate reading holding registers."""
        # For now, treat same as input registers for mocking purposes
        return await self.async_read_input_registers(unit, address, count)


@pytest.fixture
def mock_hub() -> MockHub:
    return MockHub()
