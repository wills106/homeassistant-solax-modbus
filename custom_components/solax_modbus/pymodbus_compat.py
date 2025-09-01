# pymodbus_compat.py
from __future__ import annotations
import logging
from enum import Enum


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

# Endian – prefer modern location; provide tiny shim otherwise
try:
    from pymodbus.constants import Endian  # ≥3.5 - does not exist in 3.9 anymore
except Exception:
    class Endian(Enum):
        BIG = "big"
        LITTLE = "little"


try:
    from pymodbus.client.mixin import DATATYPE
except Exception:
    class DATATYPE(Enum):
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


def _endian_str(e) -> str:
    try:
        v = getattr(e, "value", None)
        if isinstance(v, str):
            return v
        return getattr(e, "name", "BIG").lower()
    except Exception:
        s = str(e).lower()
        return "big" if "big" in s else "little"

# Decide based on installed pymodbus version
try:
    import pymodbus
    _PM_VER = _v(getattr(pymodbus, "__version__", "0.0.0"))
except Exception:
    _PM_VER = _v("0.0.0")

# Always prefer the new API for pymodbus >= 3.9.0 (where the deprecation warning appears)
# For older versions, try new API if present; otherwise fallback to legacy payload API.
_USE_NEW_API = _PM_VER >= _v("3.9.0")

# Try to import new API
_new_api_loaded = False
try:
    from pymodbus import convert_from_registers as _cfr, convert_to_registers as _ctr
    _new_api_loaded = True
except Exception:
    _new_api_loaded = False


def pymodbus_version_info():
    return f"pymodbus version {_PM_VER}, use new api: {_USE_NEW_API} new api loaded: {_new_api_loaded}"


if _USE_NEW_API and _new_api_loaded:
    # New helpers do not support a separate byte order – only word order.
    # Keep the `byteorder` parameter for caller-compat, but ignore it here.
    def convert_to_registers(value, data_type: str, wordorder):
        try:
            return _ctr(value, data_type, word_order=_endian_str(wordorder))
        except TypeError:
            return None # better to generate an error than to continue with wrong word order

    def convert_from_registers(regs, data_type: str, wordorder):
        try:
            return _cfr(regs, data_type, word_order=_endian_str(wordorder))
        except TypeError:
            return None # better to generate an error than to continue with wrong word order

else:
    # Older pymodbus or new API unavailable – try new API first, then legacy
    if _new_api_loaded:
        # New helpers available on some older versions – they still only honor word order.
        def convert_to_registers(value, data_type: str, wordorder):
            try:
                return _ctr(value, data_type, word_order=_endian_str(wordorder))
            except TypeError:
                return None # better to generate an error than to continue with wrong word order

        def convert_from_registers(regs, data_type: str, wordorder):
            try:
                return _cfr(regs, data_type, word_order=_endian_str(wordorder))
            except TypeError:
                return None  # better to generate an error than to continue with wrong word order
    else:
        # Final fallback – legacy payload API (<3.2 or very old)
        from pymodbus.payload import BinaryPayloadBuilder, BinaryPayloadDecoder  # type: ignore
        try:
            from pymodbus.constants import Endian as _OldEndian  # type: ignore
        except Exception:
            class _OldEndian(Enum):
                BIG = "big"
                LITTLE = "little"

        # Legacy path – both byte and word order are supported and applied.
        def _old_endian(e):
            return _OldEndian.BIG if _endian_str(e) == "big" else _OldEndian.LITTLE

        def convert_to_registers(value, data_type: str, wordorder):
            b = BinaryPayloadBuilder(byteorder=_OldEndian.BIG, wordorder=_old_endian(wordorder))
            dt = data_type.lower()
            if   dt == DATATYPE.UINT16:  b.add_16bit_uint(int(value))
            elif dt == DATATYPE.INT16:   b.add_16bit_int(int(value))
            elif dt == DATATYPE.UINT32:  b.add_32bit_uint(int(value))
            elif dt == DATATYPE.INT32:   b.add_32bit_int(int(value))
            elif dt == DATATYPE.FLOAT32: b.add_32bit_float(float(value))
            elif dt == DATATYPE.STRING:  b.add_string(str(value))
            else:
                raise ValueError(f"Unsupported data_type: {data_type}")
            return b.to_registers()

        def convert_from_registers(regs, data_type: str, wordorder):
            d = BinaryPayloadDecoder.fromRegisters(list(regs),
                                                  byteorder=_OldEndian.BIG, # all our plugins use this 
                                                  wordorder=_old_endian(wordorder))
            dt = data_type.lower()
            if   dt == DATATYPE.UINT16:  return d.decode_16bit_uint()
            elif dt == DATATYPE.INT16:   return d.decode_16bit_int()
            elif dt == DATATYPE.UINT32:  return d.decode_32bit_uint()
            elif dt == DATATYPE.INT32:   return d.decode_32bit_int()
            elif dt == DATATYPE.FLOAT32: return d.decode_32bit_float()
            elif dt == DATATYPE.STRING:  return d.decode_string(len(regs) * 2)
            else:
                raise ValueError(f"Unsupported data_type: {data_type}")
