# pymodbus_compat.py
from __future__ import annotations
import logging
from enum import Enum
import inspect


_LOGGER = logging.getLogger(__name__)

_STARTING = 10 # debug/info output restricted to startup

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

# Address keyword for transport calls (read/write): device_id for ≥3.10.0, else slave
try:
    ADDR_KW = "device_id" if _PM_VER >= _v("3.10.0") else "slave"
except Exception:
    ADDR_KW = "device_id"

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

# Expose official DATATYPE for modern callers (if available)
try:
    DATATYPE = getattr(pymodbus, "DATATYPE", None) if pymodbus is not None else None
except Exception:
    DATATYPE = None

# Unified datatype alias for callers: use DATATYPE when available, otherwise local DataType
DT = DATATYPE if DATATYPE is not None else DataType

# ---------------- Helpers to normalize inputs ------------------------

def _word_order_str(x) -> str:
    # normalize to "big" | "little"
    if isinstance(x, str):
        s = x.lower()
        return s if s in ("big", "little") else "big"
    v = getattr(x, "value", None)
    if isinstance(v, str) and v.lower() in ("big", "little"):
        return v.lower()
    return "big"

# ---------------- Try to access new helpers (introduced in 3.8; location varies by build) ------------------
_convert_to   = None
_convert_from = None
if pymodbus is not None:
    # 1) Preferred: module-level helpers (some newer builds)
    _convert_to   = getattr(pymodbus, "convert_to_registers", None)
    _convert_from = getattr(pymodbus, "convert_from_registers", None)

    # 2) Fallback: free functions in mixin module (some 3.9.x builds)
    if not (callable(_convert_to) and callable(_convert_from)):
        try:
            from pymodbus.client import mixin as _mixin  # type: ignore
        except Exception:
            _mixin = None
        if _mixin is not None:
            _convert_to   = getattr(_mixin, "convert_to_registers", None)
            _convert_from = getattr(_mixin, "convert_from_registers", None)

    # 3) Fallback: classmethods on ModbusClientMixin (your 3.9.2 shows them here)
    if not (callable(_convert_to) and callable(_convert_from)):
        try:
            from pymodbus.client.mixin import ModbusClientMixin as _MCM  # type: ignore
        except Exception:
            _MCM = None
        if _MCM is not None:
            _convert_to   = getattr(_MCM, "convert_to_registers", None)
            _convert_from = getattr(_MCM, "convert_from_registers", None)

    if not (callable(_convert_to) and callable(_convert_from)):
        _convert_to = _convert_from = None

# Reject helper functions that don't support word_order (e.g., very old 3.x builds)
if _convert_to and _convert_from:
    def _helper_supports_word_order(func) -> bool:
        try:
            sig = inspect.signature(func)
            # Accept if explicit kw exists, or function has at least 4 params (self, value, dt, word_order)
            return ("word_order" in sig.parameters) or (len(sig.parameters) >= 4)
        except Exception:
            # If we cannot introspect, assume new helper is ok
            return True
    if not (_helper_supports_word_order(_convert_to) and _helper_supports_word_order(_convert_from)):
        _LOGGER.debug("compat: helpers found but without word_order support; falling back to legacy payload path")
        _convert_to = _convert_from = None

# --- Ensure dt is the exact enum class PyModbus expects (DATATYPE) ---
_DT_TARGET = None
try:
    if pymodbus is not None:
        # 1) Module-level enum (preferred in newer builds)
        _DT_TARGET = getattr(pymodbus, "DATATYPE", None)
        # 2) Fallback: mixin module enum
        if _DT_TARGET is None:
            try:
                from pymodbus.client import mixin as _mixin  # type: ignore
            except Exception:
                _mixin = None
            if _mixin is not None:
                _DT_TARGET = getattr(_mixin, "DATATYPE", None)
        # 3) Fallback: enum on ModbusClientMixin class (seen in some 3.9.2 builds)
        if _DT_TARGET is None:
            try:
                from pymodbus.client.mixin import ModbusClientMixin as _MCM  # type: ignore
            except Exception:
                _MCM = None
            if _MCM is not None:
                _DT_TARGET = getattr(_MCM, "DATATYPE", None)
except Exception:
    _DT_TARGET = None

# If an official DATATYPE enum was found (module/mixin/class), alias DataType to it
try:
    if _DT_TARGET is not None and DataType is not _DT_TARGET:
        DataType = _DT_TARGET  # type: ignore
except Exception:
    pass
# Re-evaluate unified alias DT after potential aliasing of DataType
DT = DATATYPE if DATATYPE is not None else DataType

def _coerce_dt(dt):
    """Return dt as the exact pymodbus.DATATYPE member if possible.
    Accepts local DataType, pymodbus.DATATYPE, or other enum-like with .name.
    """
    if _DT_TARGET is None:
        return dt
    # already correct enum class
    try:
        if isinstance(dt, _DT_TARGET):
            return dt
    except Exception:
        pass
    # enum-like: map by name
    name = getattr(dt, "name", None)
    if isinstance(name, str) and hasattr(_DT_TARGET, name):
        return getattr(_DT_TARGET, name)
    return dt


# ---------------- Public info string ---------------------------------
def pymodbus_version_info() -> str:
    use_new = bool(_convert_to and _convert_from)
    fast_path_possible = bool(_DT_TARGET is not None and use_new)
    msg = f"pymodbus version {_PM_VER}, new api loaded: {use_new}, fast-path available: {fast_path_possible}"
    #_LOGGER.debug(msg)
    return msg


# ---------------- New helper API path (helpers found; applies to 3.8+ builds) ----------------------

if _convert_to and _convert_from:

    # start assuming fasttrack  - no coerce or wordorder adaption needed
    convert_to_registers = _convert_to
    convert_from_registers = _convert_from
    DataType = _DT_TARGET

    if _PM_VER < _v("3.9.2") : # not fast track, overwrite functions

        def convert_to_registers(value, dt: DataType, wordorder, string_encoding: str = "utf-8"):
            # Fast-path: exact enum + correct word_order string → call directly
            if _DT_TARGET is not None and isinstance(dt, _DT_TARGET) and isinstance(wordorder, str) and wordorder in ("big", "little"):
                try:
                    return _convert_to(value, dt, word_order=wordorder, string_encoding=string_encoding)
                except TypeError:
                    # Older helper with positional word order
                    return _convert_to(value, dt, wordorder)

            # Compat-path: accept local enum / mixed inputs
            dtc = _coerce_dt(dt)
            wo  = _word_order_str(wordorder)
            try:
                return _convert_to(value, dtc, word_order=wo, string_encoding=string_encoding)
            except TypeError:
                # Older 3.8 helper may only accept positional word order (and no string_encoding kw)
                return _convert_to(value, dtc, wo)

        def convert_from_registers(regs, dt: DataType, wordorder, string_encoding: str = "utf-8"):
            global _STARTING
            if _STARTING >0:
                _STARTING -= 1
                _LOGGER.debug(f"not most recent pymodbus version {_PM_VER} - not using fasttrack - using datatype and wordorder adaption")
            # Fast-path: exact enum + correct word_order string → call directly
            if _DT_TARGET is not None and isinstance(dt, _DT_TARGET) and isinstance(wordorder, str) and wordorder in ("big", "little"):
                try:
                    return _convert_from(regs, dt, word_order=wordorder, string_encoding=string_encoding)
                except TypeError:
                    # Older helper with positional word order
                    return _convert_from(regs, dt, wordorder)

            # Compat-path: accept local enum / mixed inputs
            dtc = _coerce_dt(dt)
            wo  = _word_order_str(wordorder)
            try:
                return _convert_from(regs, dtc, word_order=wo, string_encoding=string_encoding)
            except TypeError:
                return _convert_from(regs, dtc, wo)


else:
    try:
        from pymodbus.payload import BinaryPayloadBuilder, BinaryPayloadDecoder  # type: ignore
    except Exception:
        raise ImportError("The installed pymodbus version is too old and does not provide BinaryPayloadBuilder/Decoder. Please upgrade to pymodbus >= 3.8.")

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
            raise ValueError(f"Unsupported data_type: {dt}")
        return b.to_registers()

    def convert_from_registers(regs, dt: DataType, wordorder):
        if _STARTING>0: _LOGGER.warning(f"using fallback pymodbus BinaryPayloadBuilder - pymodbus {_PM_VER}")
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
            raise ValueError(f"Unsupported data_type: {dt}")
