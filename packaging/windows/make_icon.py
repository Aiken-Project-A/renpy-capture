"""The icon of renpy-capture: a line of dialogue in a viewfinder (a picture of every line), drawn with Pillow so that no
binary file has to be kept in the repository.

    python packaging/windows/make_icon.py renpy-capture.ico      the icon of the programs (build time)
    python packaging/windows/make_icon.py --png64 > renpy_capture/gui/icon.py
                                                                 the 64 pixel picture the window carries (its title
                                                                 bar and taskbar), as a module"""
import base64
import io
import sys

from PIL import Image, ImageDraw

BLUE_TOP, BLUE_BOTTOM, WHITE = (79, 141, 245), (31, 79, 209), (255, 255, 255)


def draw(size):
    """The icon at ``size`` pixels square (drawn four times as large and scaled down: smooth edges)."""
    big = size * 4
    s = big / 100                                           # one hundredth of the picture, in pixels

    def box(x0, y0, x1, y1):
        return [x0 * s, y0 * s, x1 * s - 1, y1 * s - 1]

    gradient = Image.new('RGBA', (big, big))
    for y in range(big):
        t = y / (big - 1)
        colour = tuple(round(a + (b - a) * t) for a, b in zip(BLUE_TOP, BLUE_BOTTOM)) + (255,)
        ImageDraw.Draw(gradient).line([(0, y), (big, y)], fill=colour)
    mask = Image.new('L', (big, big), 0)
    ImageDraw.Draw(mask).rounded_rectangle(box(4, 4, 96, 96), radius=22 * s, fill=255)
    img = Image.new('RGBA', (big, big), (0, 0, 0, 0))
    img.paste(gradient, (0, 0), mask)
    d = ImageDraw.Draw(img)
    w, n = 6 * s, 20 * s                                    # the viewfinder: four corners
    for cx, cy, dx, dy in ((20, 20, 1, 1), (80, 20, -1, 1), (20, 80, 1, -1), (80, 80, -1, -1)):
        x, y = cx * s, cy * s
        d.rounded_rectangle(sorted_box(x, y, x + dx * n, y + dy * w), radius=w / 2, fill=WHITE)
        d.rounded_rectangle(sorted_box(x, y, x + dx * w, y + dy * n), radius=w / 2, fill=WHITE)
    d.rounded_rectangle(box(31, 36, 69, 61), radius=6 * s, fill=WHITE)                          # the line of dialogue
    d.polygon([(37 * s, 59 * s), (50 * s, 59 * s), (36 * s, 71 * s)], fill=WHITE)               # its tail
    for y0, x1 in ((43, 62), (51, 55)):                                                         # and its words
        d.rounded_rectangle(box(37, y0, x1, y0 + 4.5), radius=2.2 * s, fill=BLUE_BOTTOM)
    return img.resize((size, size), Image.LANCZOS)


def sorted_box(x0, y0, x1, y1):
    return [min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)]


def ico(path):
    draw(256).save(path, sizes=[(n, n) for n in (16, 24, 32, 48, 64, 128, 256)])


def png64():
    """The 64 pixel icon as the PNG data of a Python module: PNG64, the picture as base64 text."""
    buf = io.BytesIO()
    draw(64).save(buf, 'PNG', optimize=True)
    text = base64.b64encode(buf.getvalue()).decode('ascii')
    lines = [f"    '{text[n:n + 96]}'" for n in range(0, len(text), 96)]
    return ('"""The icon of the window, 64 pixels (packaging/windows/make_icon.py draws it; this is its PNG file as '
            'base64\ntext, so that no binary file is kept in the repository). Made by `python '
            'packaging/windows/make_icon.py --png64`."""\nPNG64 = (\n' + '\n'.join(lines) + '\n)\n')


if __name__ == '__main__':
    if sys.argv[1:] == ['--png64']:
        print(png64(), end='')
    elif len(sys.argv) == 2:
        ico(sys.argv[1])
    else:
        sys.exit(__doc__)
