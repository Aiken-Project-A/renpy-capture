"""Everything the window says, in one place, so that it can be translated later: the labels and buttons, the sentences
about a folder, the status of a run and the summary at the end of it. The rest of the window only fills in the blanks
({name}, {n}…) and chooses which sentence to say. A phrase that counts has two forms, one and many (``count``)."""

TITLE = 'renpy-capture'

# ---- the form: what the person chooses
GAME_LABEL = 'Game folder'
BROWSE = 'Browse…'
BROWSE_GAME_TITLE = 'Choose the folder of the game'
WORK_LABEL = 'Work folder'
WORK_HELP = 'Everything is saved here. Capture again with the same folder to go on where it stopped.'
BROWSE_WORK_TITLE = 'Choose a folder for the work'
LANGUAGE_LABEL = 'Translation to capture'
LANGUAGE_ORIGINAL = "The original (the game's own language)"
TEXT_LABEL = 'Show the text box in the pictures'
TEXT_HELP = "Keeps the game's dialogue window and menus in every picture: to check how a translation fits."

VERSION_LABEL = "Ren'Py version"
VERSION_HELP = ("Choose the closest one; its engine is downloaded once. "
                "If the game does not start, try another.")
VERSION_HINT_MAJOR = "Its cache was made by Ren'Py {major}."

CAPTURE = 'Capture'
CANCEL = 'Cancel'
OPEN_PAGE = 'Open the page'
OPEN_FOLDER = 'Open the folder'
OPEN_LOG = 'Open the log'
ELAPSED = 'Time: {time}'
LOG_LABEL = 'What renpy-capture says'

# ---- the game folder
GAME_EMPTY = 'Choose the folder of the game.'
GAME_MISSING = 'This folder does not exist.'
GAME_IS_FILE = 'This is a file, not a folder. Choose the folder of the game.'
GAME_NONE = ("This does not look like a Ren'Py game: there is no \"game\" folder with .rpy, .rpyc or .rpa files in it. "
             "Choose the folder of the game (the one that holds the game's own \"game\" folder).")
GAME_SEVERAL = "There are several Ren'Py games in this folder ({names}). Choose the folder of one of them."
GAME_FOUND_VERSION = "Ren'Py game found: {name}, made with Ren'Py {version}."
GAME_FOUND_NO_VERSION = "Ren'Py game found: {name}. It does not say which version of Ren'Py made it: choose one below."

# ---- the work folder
WORK_EMPTY = 'Choose a folder to keep the work in.'
WORK_IS_FILE = 'This is a file, not a folder.'
WORK_CANNOT = 'The work folder cannot be made: {error}'
WORK_INSIDE_GAME = "The work folder and the game's folder must not be one inside the other. Choose another work folder."
WORK_OTHER_GAME = 'This folder already holds the capture of another game ({game}). Choose another work folder.'
WORK_RESUME = 'A capture of this game is in this folder: Capture goes on where it stopped.'
WORK_OTHER_FILES_TITLE = 'Use this folder?'
WORK_OTHER_FILES = ('This folder already has other files in it. renpy-capture will add its own next to them: '
                    'config.json and the folders run, out and export.\n\nUse it anyway?')
WORK_OTHER_DRIVE = ("The game is on another drive than this folder, so its files will be copied here instead of "
                    "linked: that takes room and time. A folder on the drive of the game avoids it.")
WORK_SYNCED = ("OneDrive keeps this folder in sync: it may upload the game's files that renpy-capture links here. "
               "A folder outside OneDrive is better.")

# ---- why Capture cannot start
CANNOT_START = 'The capture could not start: {error}'

# ---- while it runs: what is going on, in words
STARTING = 'Starting…'
STAGE_SETUP = 'Getting the game ready…'
STAGE_ENGINE = 'Starting the engine…'
CAPTURING = 'Capturing every branch of the game…'
STAGE_CHECK = 'Looking for scenes that no branch reached…'
STAGE_EXPORT = 'Writing the pages…'
FETCH_DOWNLOAD = "Downloading Ren'Py {version}, the engine that runs the game. This happens once, the first time."
FETCH_BYTES = '{done} of {total}'
FETCH_BYTES_UNKNOWN = '{done} so far'
FETCH_VERIFY = 'Checking the download…'
FETCH_UNPACK = "Unpacking Ren'Py {version}…"
FETCH_FILES = '{done:,} of {total:,} files'
FETCH_UNRPYC = "Downloading a small tool that reads the game's compiled scripts. This happens once."
PROGRESS_BRANCHES = 'Branches done: {done} of {total}'
PROGRESS_NOW = 'now: {job}'
PROGRESS_ENGINES = '{n} engines at work'
PROGRESS_FINISHING = 'finishing'
PROGRESS_STARTING = 'starting'
DETAIL_SEPARATOR = '   ·   '

# ---- how it ended
DONE = 'Done: {lines} in {branches}, {pictures}.'
DONE_COMPLETE = 'Every menu option was taken.'
DONE_PARTIAL = 'Some branches are still to take: press Capture again to go on.'
NOTHING_MISSED = 'Every scene of the script was reached.'
NOTHING_CAPTURED = "Nothing was captured: the game did not get as far as a line. The log has the details."
HINT_ORIGINAL = ('To see this translation beside the original, capture the original too: choose '
                 '"The original" above and press Capture.')
STOPPING = 'Stopping…'
STOPPED = 'Stopped.'
STOPPED_AT = 'It had done {done} of {total} branches and {lines}.'
STOPPED_GO_ON = 'What was captured is kept: press Capture to go on where it stopped.'
FAILED = 'renpy-capture stopped before the end.'
FAILED_NO_REASON = 'It ended without saying why (exit code {code}).'
FAILED_LOG = 'The log has the details.'
FAILED_GO_ON = 'What was captured is kept: press Capture to try again.'

WARN_ERRORS = ("{n} branch stopped on an error in the game's own script: what comes after the error in it is "
               'missing. The log names it.',
               "{n} branches stopped on an error in the game's own script: what comes after the error in them is "
               'missing. The log names them.')
WARN_MISSED = ('{n} scene of the script was not reached by any branch (maybe it needs something decided much earlier '
               'in the game).',
               '{n} scenes of the script were not reached by any branch (maybe they need something decided much '
               'earlier in the game).')
WARN_UNCHECKED = 'Could not check which scenes no branch reached: {why}'
WARN_MOVING = ('Almost every picture was taken while something on the screen was still moving (an animated overlay?): '
               'the pictures may show it half way.')
WARN_LATE = ("{n} menu with a timer was answered without waiting for the game's timer.",
             "{n} menus with a timer were answered without waiting for the game's timer.")
WARN_SLOW = 'The engine was slow: about {seconds} seconds a line. The graphics driver may be at fault.'

# ---- phrases that count: (one, many)
LINES = ('{n:,} line', '{n:,} lines')
BRANCHES = ('{n:,} branch', '{n:,} branches')
PICTURES = ('{n:,} picture', '{n:,} pictures')

# ---- questions and messages
CANCEL_TITLE = 'Stop the capture?'
CANCEL_ASK = 'What is already captured is kept, and Capture goes on from there.'
OPEN_FAILED = 'Could not open {path}.'
BUG = ("Something went wrong inside renpy-capture's window:\n\n{error}\n\nIt is written down in {path}. "
       'The window goes on, but if it misbehaves, close it and open it again.')
SELECT_ALL = 'Select all'
COPY = 'Copy'
NO_TK = ("The window needs Tk, which this Python does not have. On Debian and Ubuntu: sudo apt install python3-tk. "
         "On Windows, Python from python.org has it (re-run its installer and tick \"tcl/tk and IDLE\").")

UNITS = ('bytes', 'KB', 'MB', 'GB')


def count(forms, n):
    """A counted phrase in its form: count(LINES, 1) is "1 line", count(LINES, 2000) is "2,000 lines"."""
    return forms[0 if n == 1 else 1].format(n=n)


def size(n):
    """A number of bytes as a person reads it: 512 KB, 134.5 MB."""
    n, unit = float(n), 0
    while n >= 1024 and unit < len(UNITS) - 1:
        n, unit = n / 1024, unit + 1
    return f'{n:.0f} {UNITS[unit]}' if unit < 2 else f'{n:.1f} {UNITS[unit]}'
