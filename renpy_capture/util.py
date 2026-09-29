"""Small helpers: reading files that are closed at once, one name for a script however the engine loaded it, and words
for the lines a person reads."""
import json
import os
import re


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
    with open(path, encoding='utf-8') as f:
        return [json.loads(line) for line in f]


def script_path(fn):
    """The engine names a script `game/script.rpy` when it loads it from disk and `script.rpyc` when it loads it from
    an archive; both become the path of the .rpy source inside game/ (`script.rpy`)."""
    fn = re.sub(r'^game/', '', fn or '')
    return fn[:-1] if fn.endswith(('.rpyc', '.rpymc')) else fn


def plural(n, word, many=None):
    """"1 job", "3 jobs" ("1 branch", "2 branches" with ``many``): for the lines a person reads."""
    return f'{n} {word if n == 1 else many or word + "s"}'


def near(path):
    """A path as a person reads it: relative when it is under the current folder."""
    rel = os.path.relpath(path)
    return path if rel.startswith('..') else rel
