"""Small helpers."""
import os
import tempfile
import unittest

from renpy_capture.util import near, plural, read_json, read_jsonl, script_path


class UtilTest(unittest.TestCase):
    def test_one_name_for_a_script_however_the_engine_loaded_it(self):
        self.assertEqual(script_path('game/script.rpy'), 'script.rpy')
        self.assertEqual(script_path('script.rpyc'), 'script.rpy')          # from an archive
        self.assertEqual(script_path('game/sub/mod.rpymc'), 'sub/mod.rpym')
        self.assertEqual(script_path('game/game/x.rpy'), 'game/x.rpy')      # only the first game/ is the folder
        self.assertEqual(script_path(None), '')
        self.assertEqual(script_path(''), '')

    def test_paths_as_a_person_reads_them(self):
        self.assertEqual(near(os.path.join(os.getcwd(), 'work', 'out')), os.path.join('work', 'out'))
        self.assertEqual(near(os.path.dirname(os.getcwd())), os.path.dirname(os.getcwd()))    # above: as it is

    def test_plural(self):
        self.assertEqual(plural(1, 'branch', 'branches'), '1 branch')
        self.assertEqual(plural(2, 'branch', 'branches'), '2 branches')

    def test_json_and_jsonl_are_utf8(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, 'x')
            with open(p, 'w', encoding='utf-8') as f:
                f.write('{"a": "é"}\n{"a": 2}\n')
            self.assertEqual(read_jsonl(p), [{'a': 'é'}, {'a': 2}])
            with open(p, 'w', encoding='utf-8') as f:
                f.write('{"a": "é"}')
            self.assertEqual(read_json(p), {'a': 'é'})


if __name__ == '__main__':
    unittest.main()
