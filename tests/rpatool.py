"""Writing test archives laid out like the ones Ren'Py's own archiver (launcher/game/archiver.rpy) writes."""
import os
import pickle
import zlib


def write_rpa(path, files, version=3, key=0x5A5A1234, prefix=0, index_obj=None):
    """``files``: {name: bytes}. The index is pickled with protocol 2, as Ren'Py does."""
    with open(path, 'wb') as f:
        f.write(b'RPA-3.0 XXXXXXXXXXXXXXXX XXXXXXXX\n' if version == 3 else b'RPA-2.0 XXXXXXXXXXXXXXXX\n')
        index = {}
        for name, data in files.items():
            head, body = data[:prefix], data[prefix:]
            offset = f.tell()
            f.write(body)
            if version == 3:
                index[name] = [(offset ^ key, len(body) ^ key, head)]
            else:
                index[name] = [(offset, len(body), head)]
            f.write(b"Made with Ren'Py.")
        where = f.tell()
        f.write(zlib.compress(pickle.dumps(index if index_obj is None else index_obj, 2)))
        f.seek(0)
        f.write(b'RPA-3.0 %016x %08x\n' % (where, key) if version == 3 else b'RPA-2.0 %016x\n' % where)


def pack_game_dir(game, name='data.rpa', keep=('saves', 'cache')):
    """Move every file of a game/ folder (except ``keep``) into one archive, as a released game would ship it."""
    files = {}
    for d, subs, fs in os.walk(game):
        rel_d = os.path.relpath(d, game)
        if rel_d.split(os.sep)[0] in keep:
            subs[:] = []
            continue
        for f in fs:
            p = os.path.join(d, f)
            rel = os.path.relpath(p, game).replace(os.sep, '/')
            with open(p, 'rb') as fh:
                files[rel] = fh.read()
            os.remove(p)
    write_rpa(os.path.join(game, name), files)
    return len(files)
