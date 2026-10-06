"""Which modules of the standard library a folder of Python files imports (the build includes them: see
renpy-capture.spec)."""
import ast
import os
import sys


def stdlib_imports(folder, stdlib=None):
    """The standard-library modules that the .py files under ``folder`` import, wherever in the file: ('os', 'json',
    'concurrent.futures'), sorted. Relative imports, and files that do not parse, are left out."""
    stdlib = sys.stdlib_module_names if stdlib is None else stdlib
    found = set()
    for base, _, files in os.walk(folder):
        for name in files:
            if not name.endswith('.py'):
                continue
            with open(os.path.join(base, name), encoding='utf-8', errors='replace') as f:
                try:
                    tree = ast.parse(f.read())
                except (SyntaxError, ValueError):
                    continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    found.update(a.name for a in node.names)
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    found.add(node.module)
    return sorted(m for m in found if m.split('.')[0] in stdlib)
