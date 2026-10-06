"""Pack what PyInstaller made (dist/renpy-capture/) into the zip of a release:

    renpy-capture-<version>-windows-x64.zip
        renpy-capture/README.txt            what to do first, for a person who has never seen this
        renpy-capture/renpy-capture-gui.exe the window
        renpy-capture/renpy-capture.exe     the command line
        renpy-capture/LICENSE, THIRD-PARTY.txt
        renpy-capture/_internal/            everything they run on (Python, Tk, Pillow…)

The version is the package's own; a release workflow checks it against the tag first."""
import importlib.metadata
import os
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, ROOT)

from renpy_capture import __version__          # noqa: E402

FOLDER = 'renpy-capture'                        # the folder inside the zip


def third_party():
    """The licenses of what the build carries along (Python, Tcl/Tk, Pillow), as one text. What cannot be found is
    named, not skipped without a word."""
    parts, missing = [], []

    def add(title, path):
        if path and os.path.isfile(path):
            with open(path, encoding='utf-8', errors='replace') as f:
                parts.append(f'{"=" * 78}\n{title}\n{"=" * 78}\n\n{f.read().strip()}\n')
        else:
            missing.append(title)

    add('Python (Python Software Foundation License)', next((p for p in (
        os.path.join(sys.base_prefix, 'LICENSE.txt'), os.path.join(sys.base_prefix, 'LICENSE')) if os.path.isfile(p)),
        None))
    add('Tcl/Tk', next((os.path.join(sys.base_prefix, 'tcl', d, 'license.terms') for d in sorted(
        os.listdir(os.path.join(sys.base_prefix, 'tcl')) if os.path.isdir(os.path.join(sys.base_prefix, 'tcl'))
        else ()) if os.path.isfile(os.path.join(sys.base_prefix, 'tcl', d, 'license.terms'))), None))
    try:
        dist = importlib.metadata.distribution('Pillow')
        found = [f for f in (dist.files or []) if os.path.basename(str(f)).upper().startswith(('LICENSE', 'COPYING'))]
        add('Pillow (HPND License)', str(dist.locate_file(found[0])) if found else None)
    except importlib.metadata.PackageNotFoundError:
        missing.append('Pillow')
    for title in missing:
        parts.append(f'{title}: the license text was not found when this was built; see the project of the same name.\n')
    return '\n'.join(parts)


def main(dist=None, out=None):
    dist = dist or os.path.join(ROOT, 'dist', 'renpy-capture')
    out = out or os.path.join(os.path.dirname(dist), f'renpy-capture-{__version__}-windows-x64.zip')
    for exe in ('renpy-capture.exe', 'renpy-capture-gui.exe'):
        if not os.path.isfile(os.path.join(dist, exe)):
            sys.exit(f'{dist}: no {exe} (run PyInstaller on packaging/windows/renpy-capture.spec first)')
    with open(os.path.join(HERE, 'README.txt'), encoding='utf-8') as f:
        readme = f.read().replace('{version}', __version__)
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        z.writestr(f'{FOLDER}/README.txt', readme)
        z.write(os.path.join(ROOT, 'LICENSE'), f'{FOLDER}/LICENSE')
        z.writestr(f'{FOLDER}/THIRD-PARTY.txt', third_party())
        for base, dirs, files in os.walk(dist):
            dirs.sort()
            for name in sorted(files):
                path = os.path.join(base, name)
                z.write(path, f'{FOLDER}/{os.path.relpath(path, dist)}'.replace(os.sep, '/'))
    size = os.path.getsize(out)
    print(f'{out}: {size / 1024 ** 2:.1f} MB, {len(zipfile.ZipFile(out).namelist())} files')
    return out


if __name__ == '__main__':
    main(*sys.argv[1:3])
