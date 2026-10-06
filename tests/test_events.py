"""Machine-readable progress: one JSON object per line on the standard output, the text for a person on the standard
error, and nothing at all when it is off."""
import contextlib
import io
import json
import sys
import unittest
from unittest import mock

from renpy_capture import events


@contextlib.contextmanager
def machine_mode():
    """Machine mode over a standard output and error that are files in the code page of Windows, as a program that
    reads them (a window) sees them. Yields what each of them got, as bytes."""
    out, err = io.BytesIO(), io.BytesIO()
    streams = [io.TextIOWrapper(b, encoding='cp1252', newline='\n', write_through=True) for b in (out, err)]
    try:
        with mock.patch.object(sys, 'stdout', streams[0]), mock.patch.object(sys, 'stderr', streams[1]):
            events.enable()
            try:
                yield out, err
            finally:
                events.disable()
    finally:
        for s in streams:
            s.detach()                              # the bytes stay readable once the wrappers are gone


class EventsTest(unittest.TestCase):
    def test_off_it_does_nothing(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertFalse(events.active())
            events.emit('progress', lines=3)
        self.assertEqual(out.getvalue(), '')

    def test_events_are_json_lines_on_the_standard_output(self):
        with machine_mode() as (out, err):
            self.assertTrue(events.active())
            events.emit('stage', stage='capture')
            events.emit('progress', jobs_done=1, jobs_total=3, lines=7, now='start~1', engines=1)
        lines = out.getvalue().decode('ascii').splitlines()
        self.assertEqual([json.loads(line) for line in lines],
                         [{'event': 'stage', 'stage': 'capture'},
                          {'event': 'progress', 'jobs_done': 1, 'jobs_total': 3, 'lines': 7, 'now': 'start~1',
                           'engines': 1}])
        self.assertEqual(err.getvalue(), b'')

    def test_what_a_person_reads_goes_to_the_standard_error_in_utf8(self):
        with machine_mode() as (out, err):
            print('Привет, мир: 128 lines')
            events.emit('stage', stage='export')
        self.assertEqual(err.getvalue().decode('utf-8'), 'Привет, мир: 128 lines\n')
        self.assertEqual(len(out.getvalue().splitlines()), 1)

    def test_an_event_is_ascii_whatever_the_code_page(self):
        with machine_mode() as (out, _):
            events.emit('error', message='нет игры: C:\\Игры\\Вопрос')
        raw = out.getvalue()
        self.assertEqual(raw.decode('ascii'), raw.decode('utf-8'))
        self.assertEqual(json.loads(raw)['message'], 'нет игры: C:\\Игры\\Вопрос')

    def test_the_standard_output_is_back_when_it_ends(self):
        before = sys.stdout
        with machine_mode():
            self.assertIsNot(sys.stdout, before)
            events.enable()                         # twice: nothing is lost
        self.assertIs(sys.stdout, before)
        self.assertFalse(events.active())
        events.disable()                            # and again

    def test_a_reader_that_went_away_does_not_stop_the_capture(self):
        class Gone(io.StringIO):
            def write(self, s):
                raise BrokenPipeError

        with mock.patch.object(sys, 'stdout', Gone()), mock.patch.object(sys, 'stderr', io.StringIO()):
            events.enable()
            try:
                events.emit('progress', lines=1)
            finally:
                events.disable()

    def test_every_lets_a_few_through_and_the_last_one_always(self):
        clock = [100.0]
        with mock.patch.object(events.time, 'monotonic', lambda: clock[0]):
            tick = events.Every(0.25)
            seen = []
            for step in range(10):
                clock[0] = 100.0 + step * 0.1
                seen.append(tick(force=step == 9))
        self.assertEqual(seen, [True, False, False, True, False, False, True, False, False, True])


if __name__ == '__main__':
    unittest.main()
