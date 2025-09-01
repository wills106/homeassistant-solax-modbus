# pymodbus_compat.py
from __future__ import annotations

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
    from pymodbus.constants import Endian  # ≥3.5
except Exception:
    class Endian(Enum):
        BIG = "big"
        LITTLE = "little"

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

if _USE_NEW_API and _new_api_loaded:
    # New helpers do not support a separate byte order – only word order.
    # Keep the `byteorder` parameter for caller-compat, but ignore it here.
    def convert_to_registers(value, data_type: str, byteorder=Endian.BIG, wordorder=Endian.LITTLE):
        try:
            return _ctr(value, data_type, word_order=_endian_str(wordorder))
        except TypeError:
            return _ctr(value, data_type)

    def convert_from_registers(regs, data_type: str, byteorder=Endian.BIG, wordorder=Endian.LITTLE):
        try:
            return _cfr(regs, data_type, word_order=_endian_str(wordorder))
        except TypeError:
            return _cfr(regs, data_type)

else:
    # Older pymodbus or new API unavailable – try new API first, then legacy
    if _new_api_loaded:
        # New helpers available on some older versions – they still only honor word order.
        def convert_to_registers(value, data_type: str, byteorder=Endian.BIG, wordorder=Endian.LITTLE):
            try:
                return _ctr(value, data_type, word_order=_endian_str(wordorder))
            except TypeError:
                return _ctr(value, data_type)

        def convert_from_registers(regs, data_type: str, byteorder=Endian.BIG, wordorder=Endian.LITTLE):
            try:
                return _cfr(regs, data_type, word_order=_endian_str(wordorder))
            except TypeError:
                return _cfr(regs, data_type)
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

        def convert_to_registers(value, data_type: str, byteorder=Endian.BIG, wordorder=Endian.LITTLE):
            b = BinaryPayloadBuilder(byteorder=_old_endian(byteorder), wordorder=_old_endian(wordorder))
            dt = data_type.lower()
            if   dt == "uint16":  b.add_16bit_uint(int(value))
            elif dt == "int16":   b.add_16bit_int(int(value))
            elif dt == "uint32":  b.add_32bit_uint(int(value))
            elif dt == "int32":   b.add_32bit_int(int(value))
            elif dt == "float32": b.add_32bit_float(float(value))
            elif dt == "string":  b.add_string(str(value))
            else:
                raise ValueError(f"Unsupported data_type: {data_type}")
            return b.to_registers()

        def convert_from_registers(regs, data_type: str, byteorder=Endian.BIG, wordorder=Endian.LITTLE):
            d = BinaryPayloadDecoder.fromRegisters(list(regs),
                                                  byteorder=_old_endian(byteorder),
                                                  wordorder=_old_endian(wordorder))
            dt = data_type.lower()
            if   dt == "uint16":  return d.decode_16bit_uint()
            elif dt == "int16":   return d.decode_16bit_int()
            elif dt == "uint32":  return d.decode_32bit_uint()
            elif dt == "int32":   return d.decode_32bit_int()
            elif dt == "float32": return d.decode_32bit_float()
            elif dt == "string":  return d.decode_string(len(regs) * 2)
            else:
                raise ValueError(f"Unsupported data_type: {data_type}")
