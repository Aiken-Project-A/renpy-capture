"""Ren'Py archives (.rpa), read the way the engine reads them, without running code from the archive.

Supported: RPA-3.0 (offsets and lengths XOR a key stored in the header) and RPA-2.0, the formats Ren'Py's own
archiver writes (see ``renpy/loader.py``). The index is a zlib-compressed pickle. It is loaded by an unpickler that
refuses every global except the two Python 3 needs to rebuild ``bytes`` from pickle protocol 2, so a crafted archive
cannot execute anything on your machine. Archives with a custom header or an obfuscated index are rejected.
"""
import io
import os
import pickle
import zlib


class _IndexUnpickler(pickle.Unpickler):
    _ALLOWED = {('_codecs', 'encode'), ('builtins', 'bytes'), ('__builtin__', 'bytes')}   # protocol 2 names it so

    def find_class(self, module, name):
        if (module, name) in self._ALLOWED:
            return super().find_class(module, name)
        raise pickle.UnpicklingError(f'the archive index refers to {module}.{name}; refusing to load it')


def _load_index(data):
    return _IndexUnpickler(io.BytesIO(data), encoding='latin-1').load()


class Archive:
    """One .rpa file. ``index`` maps a file name to a list of (offset, length, prefix) segments; a file's bytes are
    each segment's prefix followed by ``length`` bytes read at ``offset``, as in ``renpy.loader.load_from_archive``."""

    def __init__(self, path):
        self.path = path
        size = os.path.getsize(path)
        with open(path, 'rb') as f:
            head = f.read(40)
            if head.startswith(b'RPA-3.0 '):
                offset, key = int(head[8:24], 16), int(head[25:33], 16)
            elif head.startswith(b'RPA-2.0 '):
                offset, key = int(head[8:24], 16), 0
            else:
                raise ValueError(f'{path}: not an RPA-2.0 or RPA-3.0 archive')
            f.seek(offset)
            raw = _load_index(zlib.decompress(f.read()))
        self.index = {}
        for name, entries in raw.items():
            segments = []
            for entry in entries:
                off, length = entry[0] ^ key, entry[1] ^ key
                prefix = entry[2] if len(entry) > 2 and entry[2] else b''
                if isinstance(prefix, str):
                    prefix = prefix.encode('latin-1')
                if off < 0 or length < 0 or off + length > size:
                    raise ValueError(f'{path}: the index does not fit the archive (custom or obfuscated format)')
                segments.append((off, length, prefix))
            self.index[name] = segments

    def read(self, name):
        out = bytearray()
        with open(self.path, 'rb') as f:
            for off, length, prefix in self.index[name]:
                out += prefix
                f.seek(off)
                out += f.read(length)
        return bytes(out)
