"""Small helpers: reading files that are closed at once, one name for a script however the engine loaded it, and words
for the lines a person reads."""
import json
import os


def read_text(path, errors='strict'):
    with open(path, encoding='utf-8', errors=errors) as f:
        return f.read()


def read_bytes(path):
    with open(path, 'rb') as f:
        return f.read()


def read_json(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def read_jsonl(path):
    """The records of a log. A line that is not JSON (an engine killed in the middle of a write) is named, with its
    number: "Unterminated string starting at: line 1" alone does not say which file."""
    with open(path, encoding='utf-8') as f:
        recs = []
        for n, line in enumerate(f, 1):
            try:
                recs.append(json.loads(line))
            except ValueError as e:
                raise ValueError(f'{path}:{n}: not a record of the log ({e})') from e
        return recs


def read_done(path):
    """The jobs a capture has finished: done.txt holds one id per line, and an id may contain spaces."""
    if not os.path.exists(path):
        return set()
    return {line for line in read_text(path).splitlines() if line}


def script_path(fn):
    """The engine names a script `game/script.rpy` when it loads it from disk and `script.rpyc` when it loads it from
    an archive; both become the path of the .rpy source inside game/ (`script.rpy`)."""
    fn = fn or ''
    if fn.startswith('game/'):
        fn = fn[5:]
    return fn[:-1] if fn.endswith(('.rpyc', '.rpymc')) else fn


def plural(n, word, many=None):
    """"1 job", "3 jobs" ("1 branch", "2 branches" with ``many``): for the lines a person reads."""
    return f'{n} {word if n == 1 else many or word + "s"}'


def near(path):
    """A path as a person reads it: relative when it is under the current folder."""
    try:
        rel = os.path.relpath(path)
    except ValueError:                              # Windows: on another drive than the current folder
        return path
    return path if rel.startswith('..') else rel
