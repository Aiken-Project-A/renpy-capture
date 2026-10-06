"""Reading a game on disk: where game/ is, files as the engine sees them, overlay mods left out, launch folders."""
import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from renpy_capture import runner
from renpy_capture.game import Game, engine_hint, engine_version, game_dir

from .rpatool import write_rpa


def linked(path, src):
    """``path`` in a launch folder is the game's file ``src``: a symbolic link to it, on Windows a hard link (or a
    copy, when the two are on different drives)."""
    if runner.WINDOWS:
        return os.path.isfile(path) and not os.path.islink(path) and os.path.samefile(path, src)
    return os.path.islink(path) and os.readlink(path) == src


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

    def test_engine_version_of_renpy_7(self):
        with open(os.path.join(self.root, 'renpy', 'vc_version.py'), 'w') as f:     # Python 2 writes u'…'
            f.write("branch = u'fix'\nnightly = False\nversion = u'7.8.7.25031702'\n")
        self.assertEqual(engine_version(self.root), '7.8.7')

    def test_a_project_inside_an_sdk_runs_on_it(self):
        sdk = os.path.join(self.tmp.name, 'renpy-8.3.2-sdk')
        os.makedirs(os.path.join(sdk, 'renpy'))
        os.makedirs(os.path.join(sdk, 'the_question', 'game', 'cache'))
        with open(os.path.join(sdk, 'renpy', 'vc_version.py'), 'w') as f:
            f.write("branch = 'fix'\nversion = '8.3.2.24090902'\n")
        open(os.path.join(sdk, 'the_question', 'game', 'script.rpy'), 'w').close()
        self.assertEqual(engine_version(os.path.join(sdk, 'the_question')), '8.3.2')

    def test_no_engine_anywhere_gives_a_hint(self):
        game = os.path.join(self.tmp.name, 'Projects', 'mine')
        os.makedirs(os.path.join(game, 'game', 'cache'))
        open(os.path.join(game, 'game', 'cache', 'bytecode-27.rpyb'), 'wb').close()
        open(os.path.join(game, 'game', 'script.rpy'), 'w').close()
        self.assertIsNone(engine_version(game))
        self.assertIn("Ren'Py 7", engine_hint(game))
        with self.assertRaises(SystemExit) as e:
            runner.setup(game, os.path.join(self.tmp.name, 'run'))
        self.assertIn("Ren'Py 7", str(e.exception))

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
        self.assertTrue(linked(os.path.join(run, 'game', 'script.rpy'), os.path.join(self.root, 'game', 'script.rpy')))
        with open(os.path.join(run, runner.RUN_INFO), encoding='utf-8') as f:
            self.assertEqual(json.load(f)['version'], '8.2.3')
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

    def test_what_the_engine_compiles_stays_in_the_launch_folder(self):
        g = os.path.join(self.root, 'game')
        os.makedirs(os.path.join(g, 'scripts'))
        with open(os.path.join(g, 'scripts', 'day1.rpy'), 'w') as f:
            f.write('label day1:\n    return\n')
        with open(os.path.join(g, 'shipped.rpy'), 'w') as f:
            f.write('label shipped:\n    return\n')
        with open(os.path.join(g, 'shipped.rpyc'), 'wb') as f:      # compiled by the author: the engine compiles
            f.write(b'rpyc')                                        # its own from the source instead
        run = os.path.join(self.tmp.name, 'run')
        rg = os.path.join(run, 'game')
        runner.setup(self.root, run)
        self.assertFalse(os.path.islink(os.path.join(rg, 'scripts')))          # a real folder with links inside
        self.assertTrue(linked(os.path.join(rg, 'scripts', 'day1.rpy'), os.path.join(g, 'scripts', 'day1.rpy')))
        self.assertFalse(os.path.lexists(os.path.join(rg, 'shipped.rpyc')))
        compiled = ('script.rpyc', 'scripts/day1.rpyc', 'shipped.rpyc')
        for p in compiled:                                                     # what the engine's first launch writes
            with open(os.path.join(rg, p), 'wb') as f:
                f.write(b'compiled here')
        runner.setup(self.root, run)                                           # every run links the folder again
        for p in compiled:                                                     # kept, not compiled again
            with open(os.path.join(rg, p), 'rb') as f:
                self.assertEqual(f.read(), b'compiled here', p)
        self.assertEqual(os.listdir(os.path.join(g, 'scripts')), ['day1.rpy'])  # the game is untouched
        with open(os.path.join(g, 'shipped.rpyc'), 'rb') as f:
            self.assertEqual(f.read(), b'rpyc')
        os.remove(os.path.join(g, 'scripts', 'day1.rpy'))                      # a script the game no longer has
        runner.setup(self.root, run)
        self.assertFalse(os.path.lexists(os.path.join(rg, 'scripts', 'day1.rpyc')))

    def test_a_file_put_there_by_hand_is_not_deleted(self):
        run = os.path.join(self.tmp.name, 'run')
        runner.setup(self.root, run)
        with open(os.path.join(run, 'game', 'images', 'notes.txt'), 'w') as f:
            f.write('mine')
        with self.assertRaises(SystemExit):
            runner.setup(self.root, run)
        self.assertTrue(os.path.exists(os.path.join(run, 'game', 'images', 'notes.txt')))

    def test_a_script_compiled_from_ren_py_is_not_linked(self):
        """The engine compiles x_ren.py into x.rpyc and writes it in place: a link there would let it write into the
        game's own x.rpyc."""
        g = os.path.join(self.root, 'game')
        with open(os.path.join(g, 'extra_ren.py'), 'w') as f:
            f.write('"""renpy\nlabel extra:\n"""\n')
        with open(os.path.join(g, 'extra.rpyc'), 'wb') as f:
            f.write(b'rpyc')
        run = os.path.join(self.tmp.name, 'run')
        runner.setup(self.root, run)
        self.assertFalse(os.path.lexists(os.path.join(run, 'game', 'extra.rpyc')))
        with open(os.path.join(run, 'game', 'extra.rpyc'), 'wb') as f:      # the engine's own
            f.write(b'compiled here')
        runner.setup(self.root, run)
        with open(os.path.join(g, 'extra.rpyc'), 'rb') as f:
            self.assertEqual(f.read(), b'rpyc')


class WindowsLaunchFolderTest(GameTest):
    """The launch folder as Windows makes it, on any system: hard links (a symbolic link needs an administrator or
    Developer Mode there), copies when a hard link cannot be made, and a list of both, since neither looks like a
    link. Every test of GameTest runs this way too."""

    def setUp(self):
        super().setUp()
        p = mock.patch.object(runner, 'WINDOWS', True)
        p.start()
        self.addCleanup(p.stop)
        self.run_dir = os.path.join(self.tmp.name, 'run')
        self.src = os.path.join(self.root, 'game', 'script.rpy')
        self.dst = os.path.join(self.run_dir, 'game', 'script.rpy')

    def setup_quietly(self, **kw):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            runner.setup(self.root, self.run_dir, **kw)
        return out.getvalue()

    def test_hard_links_and_their_list(self):
        self.setup_quietly()
        self.assertEqual(os.stat(self.src).st_nlink, 2)
        made = runner.read_json(os.path.join(self.run_dir, runner.LINKS))
        self.assertEqual(made[os.path.join('images', 'bg room.png')], 'link')
        self.assertEqual(made['script.rpy'], 'link')
        self.assertNotIn(runner.RPY_NAME, made)
        self.assertTrue(os.path.isfile(os.path.join(self.run_dir, 'bin', runner.NO_EDITOR)))
        self.setup_quietly()                                    # again: the old links go, new ones come
        self.assertEqual(os.stat(self.src).st_nlink, 2)
        shutil.rmtree(self.run_dir)                             # a launch folder deleted: the game keeps its files
        self.assertEqual(os.stat(self.src).st_nlink, 1)
        with open(self.src) as f:
            self.assertIn('label start', f.read())

    def test_a_copy_when_a_hard_link_cannot_be_made(self):
        """Another drive, FAT: the files are copied, said once, and kept while the game's file stays the same."""
        with mock.patch.object(runner.os, 'link', side_effect=OSError('not the same device')):
            said = self.setup_quietly()
            self.assertIn('copied into the launch folder', said)
            self.assertEqual(os.stat(self.src).st_nlink, 1)
            self.assertEqual(runner.read_json(os.path.join(self.run_dir, runner.LINKS))['script.rpy'], 'copy')
            before = os.stat(self.dst)
            self.assertNotIn('copied', self.setup_quietly())    # nothing changed: nothing copied again
            self.assertEqual(os.stat(self.dst).st_ino, before.st_ino)
            with open(self.src, 'a') as f:                      # the game is updated
                f.write('    "Hello again."\n')
            self.assertIn('1 file of the game copied', self.setup_quietly())
            with open(self.dst) as f:
                self.assertIn('Hello again', f.read())
            self.setup_quietly(exclude='^images$')              # a copy the game no longer wants goes
            self.assertFalse(os.path.exists(os.path.join(self.run_dir, 'game', 'images')))

    def test_a_lost_list_still_knows_its_hard_links(self):
        self.setup_quietly()
        os.remove(os.path.join(self.run_dir, runner.LINKS))
        self.setup_quietly()
        self.assertTrue(linked(self.dst, self.src))


if __name__ == '__main__':
    unittest.main()
