"""The window's brain, without a window: folders into sentences and arguments, events into words, the end of a run into a
summary, what is remembered, and the capture as a program of its own that Cancel really stops."""
import dataclasses
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from renpy_capture import sdk
from renpy_capture.gui import controller, strings as S
from renpy_capture.gui.controller import (Controller, Problem, Run, Settings, Summary, Tracker, capture_arguments,
                                          check_game, check_work, child_command, clean_path, clock_text,
                                          default_workdir, summarize)


def make_game(base, name='MyGame', version=None, cache=False, tl=(), around=()):
    """A game folder: game/script.rpy, and as asked its own engine, a cache and translations. Returns the folder."""
    root = os.path.join(base, *around, name)
    os.makedirs(os.path.join(root, 'game'))
    open(os.path.join(root, 'game', 'script.rpy'), 'w').close()
    if version:
        os.makedirs(os.path.join(root, 'renpy'))
        with open(os.path.join(root, 'renpy', 'vc_version.py'), 'w') as f:
            f.write(f"branch = 'fix'\nversion = '{version}'\n")
    if cache:
        os.makedirs(os.path.join(root, 'game', 'cache'))
        open(os.path.join(root, 'game', 'cache', 'bytecode-27.rpyb'), 'w').close()      # Ren'Py 7 on Python 2.7
    for language in tl:
        os.makedirs(os.path.join(root, 'game', 'tl', language))
    return root


class TempTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = os.path.realpath(self._tmp.name)


class PathsTest(TempTest):
    def test_what_a_person_pastes_becomes_a_path(self):
        here = os.path.abspath('.')
        self.assertEqual(clean_path(''), '')
        self.assertEqual(clean_path('   '), '')
        self.assertEqual(clean_path('""'), '')
        self.assertEqual(clean_path(f'  "{self.tmp}"  '), self.tmp)          # "Copy as path" puts quotes round it
        self.assertEqual(clean_path(f"'{self.tmp}'"), self.tmp)
        self.assertEqual(clean_path(os.path.join(self.tmp, 'a', '..', 'b')), os.path.join(self.tmp, 'b'))
        self.assertEqual(clean_path('some folder'), os.path.join(here, 'some folder'))
        with mock.patch.dict(os.environ, {'RC_TEST_HOME': self.tmp}):
            self.assertEqual(clean_path(os.path.join('$RC_TEST_HOME' if os.name != 'nt' else '%RC_TEST_HOME%', 'x')),
                             os.path.join(self.tmp, 'x'))

    def test_clock(self):
        self.assertEqual([clock_text(s) for s in (0, 9, 75, 3600, 3725)], ['0:00', '0:09', '1:15', '1:00:00', '1:02:05'])


class GameTest(TempTest):
    def test_a_game_its_game_folder_and_a_folder_around_it(self):
        root = make_game(self.tmp, version='8.2.3.24061702')
        for path in (root, os.path.join(root, 'game'), self.tmp):
            info = check_game(path)
            self.assertTrue(info.ok, path)
            self.assertEqual((info.root, info.name, info.version), (root, 'MyGame', '8.2.3'))
            self.assertIn('MyGame', info.message)
            self.assertIn('8.2.3', info.message)

    def test_a_game_that_does_not_tell_its_version_asks_for_one(self):
        info = check_game(make_game(self.tmp, cache=True))
        self.assertTrue(info.ok)
        self.assertEqual((info.version, info.major), (None, '7'))
        self.assertEqual(info.message, S.GAME_FOUND_NO_VERSION.format(name='MyGame'))

    def test_what_is_not_a_game_is_said_plainly(self):
        empty = os.path.join(self.tmp, 'Empty')
        os.makedirs(empty)
        a_file = os.path.join(self.tmp, 'MyGame.exe')
        open(a_file, 'w').close()
        for text, message in (('', S.GAME_EMPTY), (os.path.join(self.tmp, 'nothing here'), S.GAME_MISSING),
                              (a_file, S.GAME_IS_FILE), (empty, S.GAME_NONE)):
            info = check_game(text)
            self.assertEqual((info.ok, info.message), (False, message), text)

    def test_a_folder_with_several_games_names_them(self):
        make_game(self.tmp, 'Alpha', around=('Games',))
        make_game(self.tmp, 'Beta', around=('Games',))
        info = check_game(os.path.join(self.tmp, 'Games'))
        self.assertFalse(info.ok)
        self.assertEqual(info.message, S.GAME_SEVERAL.format(names='Alpha, Beta'))

    def test_a_huge_folder_is_not_searched_for_ever(self):
        make_game(self.tmp, 'Deep', around=('a',))
        with mock.patch.object(controller, 'LOOK', 2):
            self.assertEqual(check_game(self.tmp).message, S.GAME_NONE)
        self.assertTrue(check_game(self.tmp).ok)

    def test_translations_are_the_folders_of_game_tl(self):
        root = make_game(self.tmp, tl=('russian', 'French', 'None', '.hidden'))
        open(os.path.join(root, 'game', 'tl', 'notes.txt'), 'w').close()
        self.assertEqual(check_game(root).languages, ('French', 'russian'))
        self.assertEqual(check_game(make_game(self.tmp, 'Plain')).languages, ())

    def test_the_version_to_offer(self):
        self.assertEqual(controller.default_version('8'), sdk.VERSIONS[0])
        self.assertEqual(controller.default_version(None), sdk.VERSIONS[0])
        self.assertEqual(controller.default_version('7'), '7.8.7')
        self.assertEqual(controller.default_version('8', '8.2.3'), '8.2.3')        # the one chosen last time
        self.assertEqual(controller.default_version('7', '8.2.3'), '8.2.3')
        self.assertEqual(controller.default_version('8', '3.1'), sdk.VERSIONS[0])  # one that cannot be fetched is not kept


class WorkTest(TempTest):
    def setUp(self):
        super().setUp()
        self.root = make_game(self.tmp, 'Games', around=())
        self.game = check_game(self.root)
        self.work = os.path.join(self.tmp, 'work')

    def test_a_new_folder_is_fine(self):
        w = check_work(self.work, self.game)
        self.assertEqual((w.ok, w.message, w.resume, w.other_files, w.notes), (True, '', False, False, ()))
        self.assertEqual(w.path, self.work)

    def test_nothing_and_a_file_are_not_a_folder(self):
        self.assertEqual(check_work('', self.game).message, S.WORK_EMPTY)
        open(self.work, 'w').close()
        self.assertEqual(check_work(self.work, self.game).message, S.WORK_IS_FILE)

    def test_the_game_and_the_work_are_not_one_inside_the_other(self):
        for path in (os.path.join(self.root, 'work'), os.path.join(self.root, 'game'), self.root, self.tmp):
            self.assertEqual(check_work(path, self.game).message, S.WORK_INSIDE_GAME, path)

    def test_an_earlier_capture_goes_on(self):
        os.makedirs(os.path.join(self.work, 'out'))
        open(os.path.join(self.work, 'out', 'done.txt'), 'w').close()
        w = check_work(self.work, self.game)
        self.assertEqual((w.ok, w.resume, w.message), (True, True, S.WORK_RESUME))
        self.assertFalse(check_work(self.work, self.game, language='russian').resume)     # another capture, its own out
        self.assertFalse(check_work(self.work, self.game, text_box=True).resume)

    def info(self, game):
        os.makedirs(os.path.join(self.work, 'run'))
        with open(os.path.join(self.work, 'run', 'renpy-capture.json'), 'w') as f:
            json.dump({'game': game}, f)

    def test_the_capture_of_another_game_is_not_overwritten(self):
        other = make_game(self.tmp, 'Other', around=('Elsewhere',))
        self.info(other)
        w = check_work(self.work, self.game)
        self.assertEqual((w.ok, w.message), (False, S.WORK_OTHER_GAME.format(game=other)))
        self.assertTrue(check_work(self.work, check_game(other)).ok)                  # the same game: fine

    def test_the_same_game_under_another_name_is_the_same_game(self):
        self.info(os.path.join(self.root, 'game'))                  # it was given as game/ itself, now as its folder
        self.assertTrue(check_work(self.work, self.game).ok)

    def test_a_game_that_is_gone_is_no_obstacle(self):
        self.info(os.path.join(self.tmp, 'moved away'))
        self.assertTrue(check_work(self.work, self.game).ok)

    def test_a_folder_with_other_files_is_asked_about(self):
        os.makedirs(self.work)
        open(os.path.join(self.work, 'desktop.ini'), 'w').close()           # Windows adds these: not other files
        self.assertFalse(check_work(self.work, self.game).other_files)
        open(os.path.join(self.work, 'my notes.txt'), 'w').close()
        self.assertTrue(check_work(self.work, self.game).other_files)
        open(os.path.join(self.work, 'config.json'), 'w').close()           # a work folder of ours with files of its own
        self.assertFalse(check_work(self.work, self.game).other_files)

    def test_a_drive_that_is_not_the_games_is_said(self):
        with mock.patch.object(controller, 'WINDOWS', True), \
                mock.patch.object(controller, '_drive', lambda p: 'd:' if p.startswith(self.root) else 'c:'):
            self.assertEqual(check_work(self.work, self.game).notes, (S.WORK_OTHER_DRIVE,))
        self.assertEqual(check_work(self.work, self.game).notes, ())

    def test_a_folder_that_onedrive_keeps_is_said(self):
        cloud = os.path.join(self.tmp, 'OneDrive')
        with mock.patch.dict(os.environ, {'OneDrive': cloud}):
            self.assertEqual(check_work(os.path.join(cloud, 'Documents', 'x'), self.game).notes, (S.WORK_SYNCED,))
            self.assertEqual(check_work(self.work, self.game).notes, ())
            self.assertFalse(controller.synced(cloud + 'Backup'))                 # another folder with the same start

    def test_the_default_is_named_after_the_game_in_documents(self):
        docs = os.path.join(self.tmp, 'docs')
        with mock.patch.object(controller, 'documents_folder', lambda: docs):
            self.assertEqual(default_workdir(self.game), os.path.join(docs, 'renpy-capture', 'Games'))
            odd = dataclasses.replace(self.game, name='My: "Game"?')            # not a name a folder can have
            self.assertEqual(default_workdir(odd), os.path.join(docs, 'renpy-capture', 'My_ _Game__'))

    def test_the_default_of_a_game_with_the_name_of_another_is_numbered(self):
        docs = os.path.join(self.tmp, 'docs')
        os.makedirs(os.path.join(docs, 'renpy-capture', 'Games', 'run'))
        other = make_game(self.tmp, 'Other', around=('Elsewhere',))
        with open(os.path.join(docs, 'renpy-capture', 'Games', 'run', 'renpy-capture.json'), 'w') as f:
            json.dump({'game': other}, f)
        with mock.patch.object(controller, 'documents_folder', lambda: docs):
            self.assertEqual(default_workdir(self.game), os.path.join(docs, 'renpy-capture', 'Games (2)'))

    def test_documents_unless_onedrive_keeps_them(self):
        docs, home = os.path.join(self.tmp, 'Documents'), os.path.join(self.tmp, 'home')
        os.makedirs(docs)
        os.makedirs(home)
        with mock.patch.object(controller, '_xdg_documents', lambda: docs), \
                mock.patch.object(controller, 'WINDOWS', False), \
                mock.patch('os.path.expanduser', lambda p: home if p == '~' else p):
            self.assertEqual(controller.documents_folder(), docs)
            with mock.patch.dict(os.environ, {'OneDrive': self.tmp}):
                self.assertEqual(controller.documents_folder(), home)          # the work would be uploaded
        with mock.patch.object(controller, '_xdg_documents', lambda: os.path.join(self.tmp, 'gone')), \
                mock.patch('os.path.expanduser', lambda p: home if p == '~' else p):
            self.assertEqual(controller.documents_folder(), home)


class CommandTest(TempTest):
    def test_the_arguments_of_what_was_chosen(self):
        game = check_game(make_game(self.tmp, version='8.3.2.1'))
        self.assertEqual(capture_arguments(game, 'work'), ['capture', game.path, 'work', '--progress-json'])
        self.assertEqual(capture_arguments(game, 'work', 'russian', True, '7.8.7'),
                         ['capture', game.path, 'work', '--progress-json', '--language', 'russian', '--text'])

    def test_the_version_goes_only_when_the_game_does_not_tell_its_own(self):
        game = check_game(make_game(self.tmp, 'Mystery'))
        self.assertEqual(capture_arguments(game, 'work', version='8.2.3')[-2:], ['--renpy-version', '8.2.3'])
        self.assertNotIn('--renpy-version', capture_arguments(game, 'work'))

    def test_a_path_with_spaces_and_quotes_stays_one_argument(self):
        game = check_game(make_game(self.tmp, "Sylvie's Game  (v1.0)"))
        self.assertEqual(capture_arguments(game, 'my work')[1:3], [game.path, 'my work'])

    def test_not_frozen_it_is_this_python_running_the_package(self):
        self.assertEqual(child_command(), [sys.executable, '-m', 'renpy_capture'])

    def test_the_launcher_of_a_pip_installed_window_has_no_console_so_the_command_uses_python(self):
        bin_ = os.path.join(self.tmp, 'Scripts')
        os.makedirs(bin_)
        pythonw, python = os.path.join(bin_, 'pythonw.exe'), os.path.join(bin_, 'python.exe')
        open(python, 'w').close()
        with mock.patch.object(controller, 'WINDOWS', True), mock.patch.object(sys, 'executable', pythonw):
            self.assertEqual(child_command(), [python, '-m', 'renpy_capture'])

    def test_the_windows_build_starts_the_console_program_that_stands_beside_the_window(self):
        window, console = os.path.join(self.tmp, 'renpy-capture-gui.exe'), os.path.join(self.tmp, 'renpy-capture.exe')
        open(console, 'w').close()
        with mock.patch.object(controller, 'WINDOWS', True), mock.patch.object(sys, 'frozen', True, create=True), \
                mock.patch.object(sys, 'executable', window):
            self.assertEqual(child_command(), [console])
            os.remove(console)
            self.assertEqual(child_command(), [window])                            # no console program: itself


class TrackerTest(unittest.TestCase):
    def test_the_engine_is_downloaded_with_its_size_and_then_the_capture_is_counted(self):
        t = Tracker()
        self.assertEqual((t.headline(), t.detail(), t.fraction()), (S.STARTING, '', None))
        t.feed({'event': 'stage', 'stage': 'setup'})
        self.assertEqual(t.headline(), S.STAGE_SETUP)
        t.feed({'event': 'stage', 'stage': 'capture'})
        self.assertEqual((t.headline(), t.fraction()), (S.STAGE_ENGINE, None))
        t.feed({'event': 'fetch', 'what': 'sdk', 'version': '8.3.2', 'step': 'download', 'done': 70_534_000,
                'total': 141_063_916})
        self.assertEqual(t.headline(), S.FETCH_DOWNLOAD.format(version='8.3.2'))
        self.assertIn('8.3.2', t.headline())
        self.assertEqual(t.detail(), '67.3 MB of 134.5 MB')
        self.assertAlmostEqual(t.fraction(), 0.5, places=2)
        t.feed({'event': 'fetch', 'what': 'sdk', 'version': '8.3.2', 'step': 'verify'})
        self.assertEqual((t.headline(), t.detail(), t.fraction()), (S.FETCH_VERIFY, '', None))
        t.feed({'event': 'fetch', 'what': 'sdk', 'version': '8.3.2', 'step': 'unpack', 'done': 1200, 'total': 24000})
        self.assertEqual((t.headline(), t.detail()), (S.FETCH_UNPACK.format(version='8.3.2'), '1,200 of 24,000 files'))
        self.assertAlmostEqual(t.fraction(), 0.05)
        t.feed({'event': 'fetch', 'what': 'sdk', 'version': '8.3.2', 'step': 'unpack', 'done': 0, 'total': None})
        self.assertIsNone(t.fraction())                                           # a .tar.bz2: no count
        t.feed({'event': 'fetch', 'what': 'sdk', 'version': '8.3.2', 'step': 'done'})
        self.assertEqual(t.headline(), S.STAGE_ENGINE)
        t.feed({'event': 'progress', 'jobs_done': 1, 'jobs_total': 4, 'lines': 57, 'now': 'start~1', 'engines': 1})
        self.assertEqual(t.headline(), S.CAPTURING)
        self.assertEqual(t.detail(), S.DETAIL_SEPARATOR.join(['Branches done: 1 of 4', '57 lines', 'now: start~1']))
        self.assertEqual(t.fraction(), 0.25)

    def test_a_download_of_unknown_size_still_says_how_much(self):
        t = Tracker()
        t.feed({'event': 'fetch', 'what': 'sdk', 'version': '8.3.2', 'step': 'download', 'done': 3_000_000,
                'total': None})
        self.assertEqual((t.detail(), t.fraction()), ('2.9 MB so far', None))

    def test_the_tool_that_reads_compiled_scripts(self):
        t = Tracker()
        t.feed({'event': 'fetch', 'what': 'unrpyc', 'version': '2.0.4', 'step': 'download', 'done': 10, 'total': 100})
        self.assertEqual((t.headline(), t.detail()), (S.FETCH_UNRPYC, ''))

    def test_several_engines_and_the_end_of_the_branches(self):
        t = Tracker()
        t.feed({'event': 'stage', 'stage': 'capture'})
        t.feed({'event': 'progress', 'jobs_done': 1, 'jobs_total': 4, 'lines': 1, 'now': None, 'engines': 3})
        self.assertIn('3 engines at work', t.detail())
        t.feed({'event': 'progress', 'jobs_done': 4, 'jobs_total': 4, 'lines': 5, 'now': None, 'engines': 0})
        self.assertTrue(t.detail().endswith(S.PROGRESS_FINISHING))
        t.feed({'event': 'progress', 'jobs_done': 2, 'jobs_total': 4, 'lines': 5, 'now': None, 'engines': 0})
        self.assertTrue(t.detail().endswith(S.PROGRESS_STARTING))
        self.assertEqual(S.count(S.LINES, 1), '1 line')

    def test_the_steps_after_the_capture(self):
        t = Tracker()
        t.feed({'event': 'progress', 'jobs_done': 3, 'jobs_total': 3, 'lines': 128, 'now': None, 'engines': 0})
        for stage, headline in (('check', S.STAGE_CHECK), ('export', S.STAGE_EXPORT)):
            t.feed({'event': 'stage', 'stage': stage})
            self.assertEqual((t.headline(), t.detail(), t.fraction()), (headline, '', None))

    def test_an_event_with_less_than_it_should_is_no_reason_to_stop(self):
        t = Tracker()
        t.feed({'event': 'stage', 'stage': 'capture'})
        t.feed({'event': 'progress'})
        t.feed({'event': 'fetch'})
        t.feed({'event': 'something new', 'x': 1})
        t.feed({})
        for what in (t.headline, t.detail, t.fraction):
            what()


def finished_run(**done):
    """A tracker that has seen a whole capture."""
    t = Tracker()
    t.feed({'event': 'progress', 'jobs_done': 3, 'jobs_total': 3, 'lines': 128, 'now': None, 'engines': 0})
    t.feed({'event': 'done', **{'lines': 128, 'jobs': 3, 'pictures': 14, 'complete': True, 'errors': [], 'missed': 0,
                                'unchecked': None, 'warnings': [], 'language': None, 'beside': False, **done}})
    return t


class SummaryTest(TempTest):
    def test_a_capture_that_took_every_branch(self):
        s = summarize(finished_run(), 0, False)
        self.assertEqual((s.kind, s.headline), ('done', 'Done: 128 lines in 3 branches, 14 pictures.'))
        self.assertEqual(s.lines, (S.DONE_COMPLETE, S.NOTHING_MISSED))

    def test_the_page_to_open_is_the_one_that_exists(self):
        index = os.path.join(self.tmp, 'index.html')
        self.assertIsNone(summarize(finished_run(index=index), 0, False).index)
        open(index, 'w').close()
        self.assertEqual(summarize(finished_run(index=index), 0, False).index, index)

    def test_what_to_look_at_is_said_in_plain_words(self):
        s = summarize(finished_run(complete=False, errors=['start~1', 'start~2'], missed=3, language='russian',
                                   warnings=[{'kind': 'moving', 'moving': 30, 'steps': 30},
                                             {'kind': 'late', 'menus': 1}, {'kind': 'slow', 'seconds': 3.5},
                                             {'kind': 'unheard of'}]), 0, False)
        self.assertEqual(s.lines, (S.DONE_PARTIAL, S.count(S.WARN_ERRORS, 2), S.count(S.WARN_MISSED, 3), S.WARN_MOVING,
                                   S.count(S.WARN_LATE, 1), S.WARN_SLOW.format(seconds=3.5), S.HINT_ORIGINAL))
        for line in s.lines:
            self.assertNotRegex(line, r'wait_max|ui_timers|--|`')                     # nothing a config file is needed for

    def test_a_translation_beside_its_original_needs_no_hint(self):
        self.assertNotIn(S.HINT_ORIGINAL, summarize(finished_run(language='russian', beside=True), 0, False).lines)

    def test_scenes_that_could_not_be_checked(self):
        s = summarize(finished_run(unchecked='cannot download unrpyc', missed=None), 0, False)
        self.assertEqual(s.lines[1], S.WARN_UNCHECKED.format(why='cannot download unrpyc'))

    def test_a_game_that_did_not_get_as_far_as_a_line(self):
        s = summarize(finished_run(lines=0, jobs=0, pictures=0), 0, False)
        self.assertEqual(s.lines, (S.NOTHING_CAPTURED,))

    def test_stopped_by_the_person(self):
        s = summarize(finished_run(), 1, True)
        self.assertEqual((s.kind, s.headline), ('stopped', S.STOPPED))
        self.assertEqual(s.lines, (S.STOPPED_AT.format(done=3, total=3, lines='128 lines'), S.STOPPED_GO_ON))
        self.assertEqual(summarize(Tracker(), 1, True).lines, (S.STOPPED_GO_ON,))      # before the first number

    def test_a_capture_that_stopped_on_its_own_says_why(self):
        t = Tracker()
        t.feed({'event': 'error', 'message': "cannot tell the game's Ren'Py version"})
        s = summarize(t, 1, False, ['round 1: 1 job', 'a line'])
        self.assertEqual((s.kind, s.headline), ('failed', S.FAILED))
        self.assertEqual(s.lines, ("cannot tell the game's Ren'Py version", S.FAILED_LOG, S.FAILED_GO_ON))

    def test_a_crash_is_explained_by_the_last_thing_it_said(self):
        s = summarize(Tracker(), 1, False, ['Traceback (most recent call last):', 'KeyError: 3', '', '  '])
        self.assertEqual(s.lines[0], 'KeyError: 3')
        self.assertEqual(summarize(Tracker(), -9, False).lines[0], S.FAILED_NO_REASON.format(code=-9))

    def test_an_end_without_a_summary_is_not_a_success(self):
        self.assertEqual(summarize(Tracker(), 0, False).kind, 'failed')


class SettingsTest(TempTest):
    def setUp(self):
        super().setUp()
        self.path = os.path.join(self.tmp, 'config', 'renpy-capture', 'gui.json')

    def test_what_was_chosen_comes_back(self):
        s = Settings(self.path)
        self.assertEqual(s.last(), (None, {}))
        s.remember('C:/Games/Q', 'C:/Games/Q', 'C:/Docs/Q', 'russian', True, '8.3.2')
        again = Settings(self.path)
        self.assertEqual(again.last(), ('C:/Games/Q', {'workdir': 'C:/Docs/Q', 'language': 'russian', 'text': True,
                                                       'version': '8.3.2'}))
        self.assertEqual(again.game('C:/Games/Q')['workdir'], 'C:/Docs/Q')
        self.assertEqual(again.game('C:/Games/Other'), {})

    def test_each_game_keeps_its_own_choices(self):
        s = Settings(self.path)
        s.remember('/g/a', '/g/a', '/w/a', None, False, None)
        s.remember('/g/b', '/g/b', '/w/b', 'french', True, '7.8.7')
        self.assertEqual(s.game('/g/a'), {'workdir': '/w/a', 'text': False})
        self.assertEqual(s.game('/g/b')['language'], 'french')
        self.assertEqual(s.last()[0], '/g/b')

    def test_the_oldest_games_are_forgotten(self):
        s = Settings(self.path)
        for n in range(controller.KEPT_GAMES + 5):
            s.remember(f'/g/{n}', f'/g/{n}', f'/w/{n}', None, False, None)
        games = s.data['games']
        self.assertEqual(len(games), controller.KEPT_GAMES)
        self.assertEqual(s.game('/g/0'), {})
        self.assertNotEqual(s.game(f'/g/{controller.KEPT_GAMES + 4}'), {})

    def test_a_damaged_file_is_no_reason_not_to_open(self):
        os.makedirs(os.path.dirname(self.path))
        for content in ('{"last": ', '[1, 2]', '"text"', '', '\x00\x00'):
            with open(self.path, 'w') as f:
                f.write(content)
            s = Settings(self.path)
            self.assertEqual((s.last(), s.window()), ((None, {}), None), content)
            s.remember('/g', '/g', '/w', None, False, None)                           # and it is written over
            self.assertEqual(Settings(self.path).last()[0], '/g')

    def test_a_choice_of_the_wrong_kind_is_forgotten(self):
        os.makedirs(os.path.dirname(self.path))
        with open(self.path, 'w') as f:
            json.dump({'last': {'game': '/g', 'workdir': 5, 'language': ['x'], 'text': 'yes', 'version': ''},
                       'games': {'x': 'not a dict'}, 'window': {'width': 'wide', 'height': 10}}, f)
        s = Settings(self.path)
        self.assertEqual(s.last(), ('/g', {}))
        self.assertIsNone(s.window())
        s.remember('/h', '/h', '/w', None, False, None)
        self.assertNotIn('x', s.data['games'])

    def test_the_size_of_the_window(self):
        s = Settings(self.path)
        s.remember_window(800, 700)
        self.assertEqual(Settings(self.path).window(), (800, 700))

    def test_nothing_is_written_where_it_cannot_be(self):
        blocker = os.path.join(self.tmp, 'file')
        open(blocker, 'w').close()
        Settings(os.path.join(blocker, 'gui.json')).remember('/g', '/g', '/w', None, False, None)   # no error

    def test_the_config_folder(self):
        with mock.patch.object(controller, 'WINDOWS', True), mock.patch.dict(os.environ, {'APPDATA': self.tmp}):
            self.assertEqual(controller.config_dir(), os.path.join(self.tmp, 'renpy-capture'))
        with mock.patch.object(controller, 'WINDOWS', False), mock.patch.dict(os.environ, {'XDG_CONFIG_HOME': self.tmp}):
            self.assertEqual(controller.config_dir(), os.path.join(self.tmp, 'renpy-capture'))


def wait_for(run, seconds=30):
    """Everything a Run says until it has finished."""
    got, end = [], time.monotonic() + seconds
    while time.monotonic() < end:
        got += run.poll()
        if run.finished:
            return got
        time.sleep(0.02)
    run.cancel()
    raise AssertionError(f'the run did not finish in {seconds} s; it said {got[-5:]}')


class RunTest(TempTest):
    def start(self, script, **kw):
        """A capture that is a Python running ``script`` (from a file, as a program has a short command line)."""
        path = os.path.join(self.tmp, f'capture{len(os.listdir(self.tmp))}.py')
        with open(path, 'w', encoding='utf-8') as f:
            f.write(script)
        run = Run([sys.executable, path], os.path.join(self.tmp, 'run.log'), **kw)
        run.start()
        self.addCleanup(run.close)
        self.addCleanup(run.cancel)
        return run

    def test_events_text_and_the_log(self):
        run = self.start(
            'import json, sys\n'
            'print(json.dumps({"event": "stage", "stage": "setup"}), flush=True)\n'
            'sys.stderr.buffer.write("Привет, мир: 128 lines\\n".encode("utf-8")); sys.stderr.flush()\n'
            'print("not an event", flush=True)\n'
            'print("[1, 2]", flush=True)\n'
            'print(json.dumps({"event": "done", "lines": 3}), flush=True)\n'
            'sys.exit(3)\n')
        got = wait_for(run)
        self.assertEqual([x for x in got if x[0] == 'event'],
                         [('event', {'event': 'stage', 'stage': 'setup'}), ('event', {'event': 'done', 'lines': 3})])
        self.assertEqual(sorted(x[1] for x in got if x[0] == 'text'),
                         ['[1, 2]', 'not an event', 'Привет, мир: 128 lines'])
        self.assertEqual(run.returncode, 3)
        run.close()
        with open(run.log, encoding='utf-8') as f:
            lines = f.read().splitlines()
        self.assertRegex(lines[0], r'^=== \d{4}-\d\d-\d\d \d\d:\d\d:\d\d  ')
        self.assertEqual(sorted(lines[1:]), ['[1, 2]', 'not an event', 'Привет, мир: 128 lines'])   # no event in it

    def test_an_earlier_log_is_kept_and_added_to(self):
        for n in range(2):
            run = self.start(f'import sys; print("run {n}", file=sys.stderr)')
            wait_for(run)
            run.close()
        with open(run.log, encoding='utf-8') as f:
            self.assertEqual([line for line in f.read().splitlines() if not line.startswith('===')],
                             ['run 0', 'run 1'])

    def test_a_flood_of_output_is_not_a_deadlock(self):
        run = self.start('import json, sys\n'
                         'for i in range(20000):\n'
                         '    print(json.dumps({"event": "progress", "lines": i, "pad": "x" * 100}))\n'
                         '    print("a line of text number", i, "x" * 100, file=sys.stderr)\n')
        got = wait_for(run, 60)
        self.assertEqual(len([x for x in got if x[0] == 'event']), 20000)
        self.assertEqual(len([x for x in got if x[0] == 'text']), 20000)
        self.assertEqual(run.returncode, 0)

    def test_a_program_that_cannot_start_is_an_error_not_a_crash(self):
        run = Run([os.path.join(self.tmp, 'no such program')], os.path.join(self.tmp, 'run.log'))
        with self.assertRaises(OSError):
            run.start()

    @unittest.skipIf(os.name == 'nt', 'SIGTERM: Windows ends the capture and what it started by the Job Object')
    def test_cancel_stops_the_capture_the_way_ctrl_c_does(self):
        run = self.start('import sys, time\n'
                         'print("ready", file=sys.stderr, flush=True)\n'
                         'time.sleep(60)\n')
        deadline = time.monotonic() + 20
        seen = []
        while ('text', 'ready') not in seen and time.monotonic() < deadline:
            seen += run.poll()
            time.sleep(0.02)
        run.cancel()
        wait_for(run)
        self.assertTrue(run.cancelled)
        self.assertEqual(run.returncode, -signal.SIGTERM)

    @unittest.skipIf(os.name == 'nt', 'SIGKILL')
    def test_a_capture_that_does_not_stop_when_asked_is_killed(self):
        run = self.start('import signal, sys, time\n'
                         'signal.signal(signal.SIGTERM, signal.SIG_IGN)\n'
                         'print("ready", file=sys.stderr, flush=True)\n'
                         'time.sleep(60)\n')
        run.GRACE = 0.5
        deadline = time.monotonic() + 20
        seen = []
        while ('text', 'ready') not in seen and time.monotonic() < deadline:
            seen += run.poll()
            time.sleep(0.02)
        run.cancel()
        wait_for(run)
        self.assertEqual(run.returncode, -signal.SIGKILL)

    @unittest.skipUnless(os.name == 'nt', "a Job Object: the capture's engines die with the capture")
    def test_cancel_ends_what_the_capture_started_too(self):
        run = self.start('import json, subprocess, sys, time\n'
                         'p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])\n'
                         'print(json.dumps({"event": "stage", "stage": str(p.pid)}), flush=True)\n'
                         'time.sleep(60)\n')
        pid, deadline = None, time.monotonic() + 30
        while pid is None and time.monotonic() < deadline:
            for kind, payload in run.poll():
                if kind == 'event':
                    pid = int(payload['stage'])
            time.sleep(0.05)
        self.assertIsNotNone(pid)
        run.cancel()
        wait_for(run)

        def alive():
            out = subprocess.run(['tasklist', '/FI', f'PID eq {pid}', '/NH'], capture_output=True, text=True).stdout
            return str(pid) in out

        end = time.monotonic() + 15
        while alive() and time.monotonic() < end:
            time.sleep(0.2)
        self.assertFalse(alive(), 'the process the capture started is still running')

    def test_finished_waits_for_everything_that_was_said(self):
        run = self.start('import sys\nprint("last words", file=sys.stderr)\n')
        got = []
        while not run.finished:
            got += run.poll()
            time.sleep(0.01)
        got += run.poll()
        self.assertEqual(got, [('text', 'last words')])


class FakeRun:
    """A capture that says what a test tells it to."""
    made = []

    def __init__(self, argv, log, env=None):
        self.argv, self.log = argv, log
        self.said, self.code, self.cancelled, self.closed = [], None, False, False
        self.tail, self.logged, self.fail = [], [], None
        FakeRun.made.append(self)

    def start(self):
        if self.fail:
            raise self.fail

    def say(self, *items, code=None):
        self.said += items
        self.code = code

    def poll(self):
        got, self.said = self.said, []
        return got

    @property
    def finished(self):
        return self.code is not None and not self.said

    @property
    def returncode(self):
        return self.code

    def cancel(self):
        self.cancelled, self.code = True, 143

    def wait(self, seconds):
        return True

    def write_log(self, line):
        self.logged.append(line)

    def close(self):
        self.closed = True


def event(kind, **fields):
    return ('event', dict(event=kind, **fields))


class ControllerTest(TempTest):
    def setUp(self):
        super().setUp()
        FakeRun.made = []
        self.docs = os.path.join(self.tmp, 'docs')
        patch = mock.patch.object(controller, 'documents_folder', lambda: self.docs)
        patch.start()
        self.addCleanup(patch.stop)
        self.settings_path = os.path.join(self.tmp, 'cfg', 'gui.json')
        self.opened, self.now = [], [100.0]
        self.game = make_game(self.tmp, 'The Question', version='8.3.2.1', tl=('russian', 'french'), around=('games',))
        self.ctl = self.controller()

    def controller(self):
        return Controller(Settings(self.settings_path), spawn=FakeRun, opener=lambda p: self.opened.append(p) or True,
                          clock=lambda: self.now[0], command=['renpy-capture'])

    def test_nothing_chosen_yet(self):
        c = self.ctl
        self.assertEqual((c.problem(), c.can_start(), c.phase), (S.GAME_EMPTY, False, 'idle'))
        self.assertEqual(c.language_labels(), [S.LANGUAGE_ORIGINAL])
        with self.assertRaises(Problem):
            c.start()

    def test_a_game_brings_its_work_folder_and_its_translations(self):
        c = self.ctl
        c.set_game(self.game)
        self.assertTrue(c.info.ok)
        self.assertEqual(c.workdir_text, os.path.join(self.docs, 'renpy-capture', 'The Question'))
        self.assertEqual(c.language_labels(), [S.LANGUAGE_ORIGINAL, 'french', 'russian'])
        self.assertEqual((c.language_index(), c.problem(), c.can_start(), c.needs_version()), (0, None, True, False))

    def test_a_game_that_is_not_one_stops_the_button(self):
        c = self.ctl
        empty = os.path.join(self.tmp, 'empty')
        os.makedirs(empty)
        c.set_game(empty)
        self.assertEqual((c.can_start(), c.problem()), (False, S.GAME_NONE))
        c.set_game(self.game)
        c.set_workdir(os.path.join(self.game, 'work'))
        self.assertEqual(c.problem(), S.WORK_INSIDE_GAME)

    def test_a_game_without_its_version_offers_the_versions(self):
        c = self.ctl
        c.set_game(make_game(self.tmp, 'Old', cache=True, around=('old',)))
        self.assertTrue(c.needs_version())
        self.assertEqual((c.version, c.version_choices()), ('7.8.7', list(sdk.VERSIONS)))
        c.set_version('8.2.3')
        c.start()
        self.assertEqual(FakeRun.made[-1].argv[-2:], ['--renpy-version', '8.2.3'])

    def test_capture_starts_the_command_with_the_choices(self):
        c = self.ctl
        c.set_game(self.game)
        c.set_language('russian')
        c.set_text(True)
        c.set_workdir(os.path.join(self.tmp, 'my work'))
        c.start()
        run = FakeRun.made[-1]
        self.assertEqual(run.argv, ['renpy-capture', 'capture', self.game, os.path.join(self.tmp, 'my work'),
                                    '--progress-json', '--language', 'russian', '--text'])
        self.assertEqual(run.log, os.path.join(self.tmp, 'my work', 'renpy-capture.log'))
        self.assertTrue(os.path.isdir(os.path.join(self.tmp, 'my work')))
        self.assertEqual((c.phase, c.can_start()), ('running', False))

    def test_a_language_the_game_does_not_have_is_the_original(self):
        c = self.ctl
        c.set_game(self.game)
        c.set_language('klingon')
        self.assertEqual((c.language, c.language_index()), (None, 0))
        c.set_language('french')
        self.assertEqual(c.language_index(), 1)

    def test_a_run_from_start_to_summary(self):
        c = self.ctl
        c.set_game(self.game)
        c.start()
        run = FakeRun.made[-1]
        self.assertEqual((c.headline(), c.fraction()), (S.STARTING, None))
        run.say(event('stage', stage='setup'), ('text', 'launch folder: x'))
        self.assertTrue(c.pump())
        self.assertEqual((c.headline(), c.take_text(), c.take_text()), (S.STAGE_SETUP, ['launch folder: x'], []))
        self.assertFalse(c.pump())                                            # nothing new: nothing to show again
        run.say(event('stage', stage='capture'),
                event('progress', jobs_done=1, jobs_total=3, lines=57, now='start~1', engines=1))
        c.pump()
        self.assertEqual((c.headline(), c.fraction()), (S.CAPTURING, 1 / 3))
        self.assertIn('57 lines', c.detail())
        self.now[0] += 75
        self.assertEqual(c.elapsed(), 75)
        index = os.path.join(self.tmp, 'index.html')
        open(index, 'w').close()
        run.say(event('done', lines=128, jobs=3, pictures=14, complete=True, errors=[], missed=0, unchecked=None,
                      warnings=[], language=None, beside=False, index=index), code=0)
        c.pump()
        self.assertEqual((c.phase, c.summary.kind, c.headline()), ('finished', 'done',
                                                                   'Done: 128 lines in 3 branches, 14 pictures.'))
        self.assertEqual((c.detail(), c.fraction()), ('', None))
        self.assertTrue(run.closed)
        self.assertEqual(run.logged, ['=== ended with exit code 0'])
        self.now[0] += 1000
        self.assertEqual(c.elapsed(), 75)                                       # the time stops with the run
        self.assertTrue(c.can_start())                                           # and the next run can begin

    def test_the_buttons_after_a_run(self):
        c = self.ctl
        c.set_game(self.game)
        self.assertFalse(c.open_page())
        c.start()
        run = FakeRun.made[-1]
        open(run.log, 'w').close()
        index = os.path.join(self.tmp, 'index.html')
        open(index, 'w').close()
        run.say(event('done', lines=1, jobs=1, pictures=1, complete=True, errors=[], missed=0, warnings=[],
                      index=index), code=0)
        c.pump()
        self.assertTrue(c.open_page() and c.open_folder() and c.open_log())
        self.assertEqual(self.opened, [index, c.work.path, run.log])

    def test_cancel(self):
        c = self.ctl
        c.set_game(self.game)
        c.start()
        run = FakeRun.made[-1]
        run.say(event('progress', jobs_done=1, jobs_total=3, lines=57, now='start~1', engines=1))
        c.pump()
        c.cancel()
        self.assertEqual((c.headline(), run.cancelled), (S.STOPPING, True))
        c.pump()
        self.assertEqual((c.phase, c.summary.kind, c.headline()), ('finished', 'stopped', S.STOPPED))
        self.assertEqual(run.logged, ['=== ended with exit code 143 (cancelled)'])

    def test_a_capture_that_fails(self):
        c = self.ctl
        c.set_game(self.game)
        c.start()
        FakeRun.made[-1].say(event('error', message='cannot download the Ren\'Py 8.3.2 SDK'), code=1)
        c.pump()
        self.assertEqual((c.summary.kind, c.summary.lines[0]), ('failed', 'cannot download the Ren\'Py 8.3.2 SDK'))

    def test_what_cannot_be_started_is_a_sentence(self):
        c = self.ctl
        c.set_game(self.game)
        original = c.spawn

        def failing(argv, log, env=None):
            run = original(argv, log, env)
            run.fail = FileNotFoundError('no such program')
            return run

        c.spawn = failing
        with self.assertRaises(Problem) as cm:
            c.start()
        self.assertEqual(str(cm.exception), S.CANNOT_START.format(error='no such program'))
        self.assertEqual(c.phase, 'idle')
        blocker = os.path.join(self.tmp, 'a file')
        open(blocker, 'w').close()
        c.set_workdir(os.path.join(blocker, 'work'))
        with self.assertRaises(Problem) as cm:
            c.start()
        self.assertTrue(str(cm.exception).startswith(S.WORK_CANNOT.split('{')[0]))

    def test_a_work_folder_with_other_files_is_asked_about(self):
        c = self.ctl
        c.set_game(self.game)
        self.assertIsNone(c.question())
        work = os.path.join(self.tmp, 'full')
        os.makedirs(work)
        open(os.path.join(work, 'holiday.jpg'), 'w').close()
        c.set_workdir(work)
        self.assertEqual(c.question(), S.WORK_OTHER_FILES)

    def test_the_last_choices_come_back_next_time(self):
        c = self.ctl
        c.set_game(self.game)
        c.set_language('russian')
        c.set_text(True)
        c.set_workdir(os.path.join(self.tmp, 'my work'))
        c.start()
        again = self.controller()
        self.assertEqual((again.game_text, again.info.ok, again.language, again.text, again.workdir_text),
                         (self.game, True, 'russian', True, os.path.join(self.tmp, 'my work')))
        self.assertTrue(again.can_start())

    def test_each_game_gets_its_work_folder_back(self):
        c = self.ctl
        other = make_game(self.tmp, 'Other', version='8.3.2.1', around=('more',))
        c.set_game(self.game)
        c.set_workdir(os.path.join(self.tmp, 'one'))
        c.start()
        c.cancel()
        c.pump()
        c.set_game(other)
        self.assertEqual(c.workdir_text, os.path.join(self.docs, 'renpy-capture', 'Other'))   # not the first game's
        c.set_game(self.game)
        self.assertEqual(c.workdir_text, os.path.join(self.tmp, 'one'))

    def test_the_same_game_typed_again_keeps_what_was_chosen(self):
        c = self.ctl
        c.set_game(self.game)
        c.set_language('french')
        c.set_workdir(os.path.join(self.tmp, 'mine'))
        c.set_game(self.game + os.sep)                                          # the same folder, a slash more
        c.set_game(os.path.join(self.tmp, 'nothing here'))                      # a mistake in between
        self.assertFalse(c.info.ok)
        c.set_game(self.game)
        self.assertEqual((c.language, c.workdir_text), ('french', os.path.join(self.tmp, 'mine')))

    def test_closing_the_window_stops_a_capture(self):
        c = self.ctl
        c.set_game(self.game)
        c.start()
        run = FakeRun.made[-1]
        c.close()
        self.assertTrue(run.cancelled and run.closed)
        self.assertIsNone(c.run)
        c.close()                                                               # again: nothing to do

    def test_before_a_run_there_is_no_time_and_no_log_to_open(self):
        self.assertEqual(self.ctl.elapsed(), 0)
        self.assertFalse(self.ctl.open_log())
        self.assertFalse(self.ctl.pump())


class StringsTest(unittest.TestCase):
    def test_counted_phrases(self):
        self.assertEqual([S.count(S.LINES, n) for n in (0, 1, 2, 21945)], ['0 lines', '1 line', '2 lines', '21,945 lines'])
        self.assertEqual(S.count(S.BRANCHES, 1), '1 branch')

    def test_sizes(self):
        self.assertEqual([S.size(n) for n in (0, 512, 2048, 5 * 1024 ** 2, 141_063_916, 3 * 1024 ** 3)],
                         ['0 bytes', '512 bytes', '2 KB', '5.0 MB', '134.5 MB', '3.0 GB'])

    def test_every_sentence_is_used_and_the_words_are_only_here(self):
        """A string nobody says is clutter for the translator; a sentence outside this file cannot be translated."""
        here = os.path.dirname(controller.__file__)
        said = ''.join(open(os.path.join(here, name), encoding='utf-8').read()
                       for name in ('controller.py', 'app.py', '__init__.py') if os.path.exists(os.path.join(here, name)))
        names = [n for n in vars(S) if n.isupper() and n != 'UNITS']
        self.assertTrue(names)
        for name in names:
            self.assertRegex(said, rf'\b(?:S|strings)\.{name}\b', name)


if __name__ == '__main__':
    unittest.main()
