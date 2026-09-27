"""Reading a game on disk: where game/ is, files as the engine sees them, overlay mods left out, launch folders."""
import json
import os
import tempfile
import unittest

from renpy_capture import runner
from renpy_capture.game import Game, engine_version, game_dir

from .rpatool import write_rpa


class GameTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = os.path.join(self.tmp.name, 'Wrapped', 'MyGame-1.0-pc')
        g = os.path.join(self.root, 'game')
        os.makedirs(os.path.join(g, 'images'))
        os.makedirs(os.path.join(self.root, 'renpy'))
        with open(os.path.join(self.root, 'renpy', 'vc_version.py'), 'w') as f:
            f.write("branch = 'fix'\nversion = '8.2.3.24061702'\nversion_name = 'x'\n")
        with open(os.path.join(g, 'script.rpy'), 'w') as f:
            f.write('label start:\n    scene bg room\n    "Hello."\n')
        with open(os.path.join(g, 'images', 'bg room.png'), 'wb') as f:
            f.write(b'loose')
        write_rpa(os.path.join(g, 'images.rpa'), {'images/bg room.png': b'archived', 'images/cg 1.png': b'cg'})
        write_rpa(os.path.join(g, 'Translator3000.rpa'), {'translator3000.rpy': b'label overlay:\n    show x\n'})
        os.makedirs(os.path.join(g, '_translator3000_fonts'))

    def tearDown(self):
        self.tmp.cleanup()

    def test_game_dir_is_found_below(self):
        self.assertEqual(game_dir(self.tmp.name), os.path.join(self.root, 'game'))
        self.assertEqual(game_dir(os.path.join(self.root, 'game')), os.path.join(self.root, 'game'))

    def test_engine_version(self):
        self.assertEqual(engine_version(self.root), '8.2.3')

    def test_loose_files_win_and_mods_are_left_out(self):
        g = Game(self.root)
        self.assertEqual(g.files['images/bg room.png'](), b'loose')
        self.assertEqual(g.files['images/cg 1.png'](), b'cg')
        self.assertFalse([f for f in g.files if 'translator3000' in f.lower()])
        self.assertEqual(list(g.scripts()), ['script.rpy'])

    def test_launch_folder(self):
        run = os.path.join(self.tmp.name, 'run')
        runner.setup(self.root, run)
        names = sorted(os.listdir(os.path.join(run, 'game')))
        self.assertIn('script.rpy', names)
        self.assertIn(runner.RPY_NAME, names)
        self.assertFalse([n for n in names if 'translator3000' in n.lower()])
        self.assertTrue(os.path.islink(os.path.join(run, 'game', 'script.rpy')))
        self.assertEqual(json.load(open(os.path.join(run, runner.RUN_INFO)))['version'], '8.2.3')
        with open(os.path.join(run, 'game', 'cache', 'bytecode-39.rpyb'), 'wb') as f:
            f.write(b'kept')
        with open(os.path.join(self.root, 'game', 'new.rpy'), 'w') as f:
            f.write('label new:\n    return\n')
        runner.setup(self.root, run)                # again: follows the game, keeps the engine's cache
        self.assertIn('new.rpy', os.listdir(os.path.join(run, 'game')))
        self.assertTrue(os.path.exists(os.path.join(run, 'game', 'cache', 'bytecode-39.rpyb')))

    def test_launch_folder_is_not_the_game(self):
        with self.assertRaises(SystemExit):
            runner.setup(self.root, self.root)


if __name__ == '__main__':
    unittest.main()
