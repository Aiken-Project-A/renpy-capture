# Temporary, for windows-probe.yml: the sizes of the frames of a capture, and how many are one flat colour.
import collections
import os
import sys

from PIL import Image

out = sys.argv[1]
frames = os.path.join(out, 'frames')
sizes, flat = collections.Counter(), 0
names = sorted(os.listdir(frames)) if os.path.isdir(frames) else []
for n in names:
    with Image.open(os.path.join(frames, n)) as im:
        sizes[im.size] += 1
        ext = im.convert('RGB').getextrema()
        flat += all(lo == hi for lo, hi in ext)
print(f'{len(names)} frames, sizes {dict(sizes)}, flat {flat}')
