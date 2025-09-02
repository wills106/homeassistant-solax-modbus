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
    _PM_VER = _v("0.0.0")

# Always prefer the new API for pymodbus >= 3.9.0 (where the deprecation warning appears)
# For older versions, try new API if present; otherwise fallback to legacy payload API.
_USE_NEW_API = _PM_VER >= _v("3.9.0")




class compat_DATATYPE(Enum):
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


def check_modbus_compat(name, client, force_old_api = False):
    dt = getattr(client, "DATATYPE", None) # new style pymodbus
    if dt is None:
        _new_api_loaded = False
        DATATYPE = compat_DATATYPE
        _LOGGER.warning(f"{name} probably using old pymodbus version - compat fallback")
        client.DATATYPE = DATATYPE
    else:
        _new_api_loaded = True


    if not _new_api_loaded or force_old_api:

        # Final fallback – legacy payload API (<3.2 or very old)
        global BinaryPayloadBuilder
        global BinaryPayloadDecoder

        try:
            from pymodbus.payload import BinaryPayloadBuilder, BinaryPayloadDecoder  # type: ignore
        except Exception: 
            from .payload import BinaryPayloadBuilder, BinaryPayloadDecoder  # type: ignore - Should not be needed anymore

        try:
            from pymodbus.constants import Endian as _OldEndian  # type: ignore
        except Exception:
            #class _OldEndian(Enum):
            #    BIG = "big"
            #    LITTLE = "little"
            class _OldEndian(str, Enum):
                AUTO = "@"
                BIG = ">"
                LITTLE = "<"     

        # Legacy path – both byte and word order are supported and applied.
        def _old_endian(e):
            return _OldEndian.BIG if e == "big" else _OldEndian.LITTLE

        def convert_to_registers(client, value, dt: DATATYPE, wordorder):
            b = BinaryPayloadBuilder(byteorder=_OldEndian.BIG, wordorder=_old_endian(wordorder))
            if   dt == DATATYPE.UINT16:  b.add_16bit_uint(int(value))
            elif dt == DATATYPE.INT16:   b.add_16bit_int(int(value))
            elif dt == DATATYPE.UINT32:  b.add_32bit_uint(int(value))
            elif dt == DATATYPE.INT32:   b.add_32bit_int(int(value))
            elif dt == DATATYPE.FLOAT32: b.add_32bit_float(float(value))
            elif dt == DATATYPE.STRING:  b.add_string(str(value))
            else:
                raise ValueError(f"Unsupported data_type: {data_type}")
            return b.to_registers()

        def convert_from_registers(client, regs, dt: DATATYPE, wordorder):
            d = BinaryPayloadDecoder.fromRegisters(list(regs),
                                                  byteorder=_OldEndian.BIG, # all our plugins use this 
                                                  wordorder=_old_endian(wordorder))
            if   dt == DATATYPE.UINT16:  return d.decode_16bit_uint()
            elif dt == DATATYPE.INT16:   return d.decode_16bit_int()
            elif dt == DATATYPE.UINT32:  return d.decode_32bit_uint()
            elif dt == DATATYPE.INT32:   return d.decode_32bit_int()
            elif dt == DATATYPE.FLOAT32: return d.decode_32bit_float()
            elif dt == DATATYPE.STRING:  return d.decode_string(len(regs) * 2)
            else:
                raise ValueError(f"Unsupported data_type: {data_type}")

    if getattr(client, "convert_to_registers", None) is None: client.convert_to_registers = convert_to_registers
    if getattr(client, "convert_from_registers", None) is None: client.convert_from_registers = convert_from_registers

    return f"pymodbus version {_PM_VER}, use new api: {_USE_NEW_API} new api loaded: {_new_api_loaded}"


