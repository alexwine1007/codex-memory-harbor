"""Fresh macOS volume UUID checks, with a bounded command-line fallback.

No success cache: every checkpoint queries the mounted filesystem again.
ABI constants are from the macOS SDK sys/attr.h and Apple's getattrlist(2).
"""
import ctypes
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import uuid


class AttrList(ctypes.Structure):
    _fields_ = [('bitmapcount', ctypes.c_ushort), ('reserved', ctypes.c_ushort),
                ('commonattr', ctypes.c_uint32), ('volattr', ctypes.c_uint32),
                ('dirattr', ctypes.c_uint32), ('fileattr', ctypes.c_uint32),
                ('forkattr', ctypes.c_uint32)]


def native_uuid(path):
    if sys.platform != 'darwin':
        raise NotImplementedError('macOS volume attributes unavailable')
    library = ctypes.CDLL(None, use_errno=True)
    call = library.getattrlist
    call.argtypes = [ctypes.c_char_p, ctypes.POINTER(AttrList), ctypes.c_void_p,
                     ctypes.c_size_t, ctypes.c_ulong]
    call.restype = ctypes.c_int
    attributes = AttrList(5, 0, 0, 0x80000000 | 0x00040000, 0, 0, 0)
    output = ctypes.create_string_buffer(20)
    if call(os.fsencode(path), ctypes.byref(attributes), output, len(output), 0):
        raise OSError(ctypes.get_errno(), 'volume UUID query failed')
    if int.from_bytes(output.raw[:4], sys.byteorder) != 20 or not any(output.raw[4:]):
        raise OSError('invalid volume UUID response')
    return str(uuid.UUID(bytes=output.raw[4:20])).upper()


def fresh_uuid(path):
    path = Path(path)
    if path.parent != Path('/Volumes') or path.is_symlink() or not os.path.ismount(path):
        raise RuntimeError('外置卷未挂载，停止操作')
    try:
        return native_uuid(path)
    except (OSError, AttributeError, NotImplementedError):
        result = subprocess.run(['diskutil', 'info', '-plist', str(path)],
                                capture_output=True, timeout=3, check=True)
        info = plistlib.loads(result.stdout)
        identity = info.get('VolumeUUID') or info.get('APFSVolumeUUID') or info.get('MediaUUID')
        if not identity or info.get('MountPoint') != str(path):
            raise RuntimeError('无法确认外置卷持久身份，停止操作')
        return str(identity).upper()
