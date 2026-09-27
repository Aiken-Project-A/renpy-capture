"""The RPA reader: archives as Ren'Py's archiver writes them, and archives that try to run code."""
import os
import pickle
import tempfile
import unittest

from renpy_capture.rpa import Archive

from .rpatool import write_rpa


class Payload:
    def __init__(self, marker):
        self.marker = marker

    def __reduce__(self):
        return (open, (self.marker, 'w'))


class RPATest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.files = {'script.rpy': 'label start:\n    "Hello."\n'.encode(),
                      'images/bg room.png': os.urandom(3000),
                      'музыка/тема.ogg': os.urandom(500)}

    def tearDown(self):
        self.tmp.cleanup()

    def path(self, name='a.rpa'):
        return os.path.join(self.tmp.name, name)

    def test_v3(self):
        write_rpa(self.path(), self.files)
        a = Archive(self.path())
        self.assertEqual(sorted(a.index), sorted(self.files))
        for name, data in self.files.items():
            self.assertEqual(a.read(name), data)

    def test_v2(self):
        write_rpa(self.path(), self.files, version=2)
        a = Archive(self.path())
        for name, data in self.files.items():
            self.assertEqual(a.read(name), data)

    def test_prefix_is_not_part_of_the_length(self):
        write_rpa(self.path(), self.files, prefix=7)
        a = Archive(self.path())
        for name, data in self.files.items():
            self.assertEqual(a.read(name), data)

    def test_code_in_the_index_is_refused(self):
        marker = self.path('pwned')
        write_rpa(self.path(), {}, index_obj={'x': Payload(marker)})
        with self.assertRaises(pickle.UnpicklingError):
            Archive(self.path())
        self.assertFalse(os.path.exists(marker))

    def test_wrong_key_is_rejected(self):
        write_rpa(self.path(), self.files)
        with open(self.path(), 'r+b') as f:
            f.seek(25)
            f.write(b'00000000')
        with self.assertRaises(ValueError):
            Archive(self.path())

    def test_not_an_archive(self):
        with open(self.path(), 'wb') as f:
            f.write(b'ALT-1.0 whatever\n')
        with self.assertRaises(ValueError):
            Archive(self.path())


if __name__ == '__main__':
    unittest.main()
