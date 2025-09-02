# pymodbus_compat.py
from __future__ import annotations
import logging
from enum import Enum


_LOGGER = logging.getLogger(__name__)

# Version parsing – prefer packaging, fallback to a tiny tuple parser
try:
    from packaging.version import parse as _v  # type: ignore
except Exception:  # packaging may be absent in some environments
    def _v(s: str):  # minimal semantic-ish parser: converts 'X.Y.Z' -> (X,Y,Z)
        parts = []
        for p in str(s).split('.'):
            try:
                parts.append(int(p))
            except Exception:
                break
        while len(parts) < 3:
            parts.append(0)
        return tuple(parts)


# Decide based on installed pymodbus version
try:
    import pymodbus
    _PM_VER = _v(getattr(pymodbus, "__version__", "0.0.0"))
except Exception:
    pymodbus = None  # type: ignore
    _PM_VER = _v("0.0.0")

# Always prefer the new API for pymodbus >= 3.9.0 (where the deprecation warning appears)
# For older versions, try new API if present; otherwise fallback to legacy payload API.
_USE_NEW_API = _PM_VER >= _v("3.9.0")



# ---------------- Public DataType enum (single source of truth) ------
# Prefer the official pymodbus DATATYPE if available (future-proof), otherwise use a local enum.
_DataTypeAlias = getattr(pymodbus, "DATATYPE", None) if pymodbus is not None else None
if _DataTypeAlias is not None:
    DataType = _DataTypeAlias  # alias to official enum (values are expected to stringify to new helper tokens)
else:
    class DataType(Enum):
        """Datatype enum (name and internal data), used for convert_* calls."""
        INT16 = ("h", 1)
        UINT16 = ("H", 1)
        INT32 = ("i", 2)
        UINT32 = ("I", 2)
        INT64 = ("q", 4)
        UINT64 = ("Q", 4)
        FLOAT32 = ("f", 2)
        FLOAT64 = ("d", 4)
        STRING = ("s", 0)
        BITS = ("bits", 0)

# ---------------- Helpers to normalize inputs ------------------------
#def _dt_str(x) -> str:
#    return x.value if isinstance(x, DataType) else str(x).lower()

def _word_order_str(x) -> str:
    # normalize to "big" | "little"
    if isinstance(x, str):
        s = x.lower()
        return s if s in ("big", "little") else "big"
    v = getattr(x, "value", None)
    if isinstance(v, str) and v.lower() in ("big", "little"):
        return v.lower()
    return "big"

# ---------------- Try to access new helpers (≥ 3.9) ------------------
_convert_to   = None
_convert_from = None
if _USE_NEW_API and pymodbus and pymodbus.client and pymodbus.client.mixin and pymodbus.client.mixin.ModbusClientMixin :
    _convert_to = getattr(pymodbus.client.mixin.ModbusClientMixin, "convert_to_registers", None)
    _convert_from = getattr(pymodbus.client.mixin.ModbusClientMixin, "convert_from_registers", None)
    if not callable(_convert_to) or not callable(_convert_from):
        _convert_to = _convert_from = None


# ---------------- Public info string ---------------------------------
def pymodbus_version_info() -> str:
    return (
        f"pymodbus version {_PM_VER}, use new api: {_USE_NEW_API} "
        f"new api loaded: {bool(_convert_to and _convert_from)}"
    )


# ---------------- New helper API path (≥ 3.9.0) ----------------------

if _convert_to and _convert_from:
    convert_to_registers = _convert_to
    convert_from_registers = _convert_from

else:
    try:
        from pymodbus.payload import BinaryPayloadBuilder, BinaryPayloadDecoder  # type: ignore
    except Exception: 
        from .payload import BinaryPayloadBuilder, BinaryPayloadDecoder  # type: ignore - Should not be needed anymore

    try:
        from pymodbus.constants import Endian as _OldEndian  # type: ignore
    except Exception:
        class _OldEndian(str, Enum):
            AUTO = "@"
            BIG = ">"
            LITTLE = "<"     

        # Legacy path – both byte and word order are supported and applied.
    def _old_endian(e):
        return _OldEndian.BIG if _word_order_str(e) == "big" else _OldEndian.LITTLE

    def convert_to_registers(value, dt: DataType, wordorder):
        b = BinaryPayloadBuilder(byteorder=_OldEndian.BIG, wordorder=_old_endian(wordorder))
        if   dt == DataType.UINT16:  b.add_16bit_uint(int(value))
        elif dt == DataType.INT16:   b.add_16bit_int(int(value))
        elif dt == DataType.UINT32:  b.add_32bit_uint(int(value))
        elif dt == DataType.INT32:   b.add_32bit_int(int(value))
        elif dt == DataType.FLOAT32: b.add_32bit_float(float(value))
        elif dt == DataType.STRING:  b.add_string(str(value))
        else:
            raise ValueError(f"Unsupported data_type: {data_type}")
        return b.to_registers()

    def convert_from_registers(regs, dt: DataType, wordorder):
        d = BinaryPayloadDecoder.fromRegisters(list(regs),
                                                byteorder=_OldEndian.BIG, # all our plugins use this 
                                                wordorder=_old_endian(wordorder))
        if   dt == DataType.UINT16:  return d.decode_16bit_uint()
        elif dt == DataType.INT16:   return d.decode_16bit_int()
        elif dt == DataType.UINT32:  return d.decode_32bit_uint()
        elif dt == DataType.INT32:   return d.decode_32bit_int()
        elif dt == DataType.FLOAT32: return d.decode_32bit_float()
        elif dt == DataType.STRING:  return d.decode_string(len(regs) * 2)
        else:
            raise ValueError(f"Unsupported data_type: {data_type}")


