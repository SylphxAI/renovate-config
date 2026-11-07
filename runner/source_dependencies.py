"""Conservative source-directory closure for action/workflow consumption.

A reached file enrolls its complete directory tree (the whole action tree for
an action). Literal paths, local uses and Python imports can only add trees;
precise import tracing must never narrow this coarse lower bound. Unresolved
local consumption is unknown, not proof that a consumer has no dependencies.
"""
from __future__ import annotations

import ast
import posixpath
import re

import yaml


class DependencyUnknown(ValueError):
    """The immutable source does not prove a complete local dependency set."""


_CODE = ('.yml', '.yaml', '.py', '.sh', '.bash', '.js', '.mjs', '.cjs', '.ts', '.tsx')
_ACTION = re.compile(r'(\.github/actions/[^/]+)(?:/|$)')
_ACTION_PATH = re.compile(r'(?:\$GITHUB_ACTION_PATH|\$\{GITHUB_ACTION_PATH\}|'
                          r'\$\{\{\s*github\.action_path\s*\}\})(/[\w./${}-]+)?')
_PATH = re.compile(r'(?<![\w.-])((?:scripts/|\.github/(?:actions|workflows)/|\./|\.\./)[\w./-]+)')
_LITERAL = re.compile(r'''["']([\w./-]+)["']''')


def dependency_paths(roots, source_paths, read):
    """Return all blob paths in the coarse, transitively reached directories.

    ``source_paths`` must be a complete tree inventory, not just code files.
    External Python imports are not local references; explicit relative imports,
    local uses and action-relative paths must resolve or raise DependencyUnknown.
    """
    paths = set(source_paths)
    directories = {posixpath.dirname(path) for path in paths}
    for directory in tuple(directories):
        while directory:
            directory = posixpath.dirname(directory)
            directories.add(directory)
    suffixes, members = {}, {}
    for candidate in paths | directories:
        parts = candidate.split('/')
        for index in range(len(parts)):
            suffixes.setdefault('/'.join(parts[index:]), set()).add(candidate)
    for path in paths:
        directory = posixpath.dirname(path)
        while True:
            members.setdefault(directory, set()).add(path)
            if not directory:
                break
            directory = posixpath.dirname(directory)
    selected, scanned, pending, enrolled, executables, queued = set(), set(), [], set(), set(), set()

    def queue(path):
        if path not in scanned and path not in queued:
            queued.add(path)
            pending.append(path)

    def enroll(reference, *, required=False, executable=False):
        reference = posixpath.normpath(reference).rstrip('/')
        if reference == '..' or reference.startswith('../') or reference.startswith('/'):
            if required:
                raise DependencyUnknown('local-path-outside-source:' + reference)
            return False
        if reference not in paths and reference not in directories:
            if required:
                raise DependencyUnknown('local-path-missing:' + reference)
            return False
        action = _ACTION.match(reference)
        directory = (action.group(1) if action else
                     posixpath.dirname(reference) if reference in paths else reference)
        if directory not in members:
            raise DependencyUnknown('local-directory-unresolved:' + reference)
        if executable and reference in paths:
            executables.add(reference)
            queue(reference)
        if directory not in enrolled:
            enrolled.add(directory)
            selected.update(members[directory])
            for path in sorted(members[directory]):
                if not path.endswith(('.yml', '.yaml')):
                    queue(path)
        # Inclusion of a YAML template/fixture is not proof it executes. Only
        # declared roots/local uses and actual action manifests execute YAML.
        if executable and reference in paths and reference.endswith(('.yml', '.yaml')):
            queue(reference)
        if action:
            for path in (directory + '/action.yml', directory + '/action.yaml'):
                if path in paths:
                    queue(path)
        return True

    if not roots or any(not root for root in roots):
        raise DependencyUnknown('local-consumption-unresolved')
    for root in roots:
        enroll(root.removeprefix('./'), required=True, executable=True)

    aliases = {}

    def local(reference):
        reference = reference.removeprefix('./')
        for alias in sorted(aliases, key=len, reverse=True):
            if reference == alias or reference.startswith(alias + '/'):
                return posixpath.join(aliases[alias], reference[len(alias):].lstrip('/'))
        return reference

    def resolve(reference, path, *, required=False):
        # Both source-root and current-file-relative paths are conservative
        # candidates. Never pick just one when both exist.
        found = enroll(local(reference), executable=required)
        found = enroll(posixpath.join(posixpath.dirname(path), reference), executable=required) or found
        if not found and required:
            raise DependencyUnknown('local-reference-missing:' + path + ':' + reference)
        return found

    while pending:
        path = pending.pop()
        queued.discard(path)
        if path in scanned:
            continue
        scanned.add(path)
        if not path.endswith(_CODE):
            if path in executables:
                raise DependencyUnknown('executable-source-type-unknown:' + path)
            continue
        text = read(path)
        aliases = {}
        if path.endswith(('.yml', '.yaml')):
            try:
                document = yaml.safe_load(text)
            except yaml.YAMLError as error:
                raise DependencyUnknown('yaml-source-unparseable:' + path) from error
            seen = set()
            def checkouts(value):
                if id(value) in seen:
                    return
                seen.add(id(value))
                if isinstance(value, dict):
                    fields = value.get('with', {})
                    if (str(value.get('uses', '')).lower().startswith('actions/checkout@')
                            and isinstance(fields, dict)
                            and str(fields.get('repository', '')).lower() == 'sylphxai/.github'):
                        destination = fields.get('path')
                        if isinstance(destination, str) and destination and '$' not in destination:
                            aliases[destination.removeprefix('./').rstrip('/')] = ''
                    for child in value.values():
                        checkouts(child)
                elif isinstance(value, list):
                    for child in value:
                        checkouts(child)
            checkouts(document)
        # A literal copy of pinned action tools preserves their source directory
        # after materialization (including a loop over dynamic tool filenames).
        action = _ACTION.match(path)
        if action:
            for source, destination in re.findall(r'cp\s+[\'"]?\$GITHUB_ACTION_PATH(/[\w./${}-]+)[\'"]?\s+[\'"]?([\w./${}-]+)', text):
                source_dir = posixpath.dirname(source.split('$', 1)[0] + ('_' if '$' in source else ''))
                destination_dir = posixpath.dirname(destination.split('$', 1)[0] + ('_' if '$' in destination else ''))
                origin = posixpath.normpath(action.group(1) + source_dir)
                if origin in directories and destination_dir:
                    aliases[destination_dir] = origin
        for match in _ACTION_PATH.finditer(text):
            action = _ACTION.match(path)
            if not action:
                continue  # Generators can contain action templates as data.
            suffix = match.group(1) or ''
            # A dynamic leaf is covered by its literal directory, never empty.
            static = re.split(r'\$', suffix, maxsplit=1)[0]
            if static != suffix:
                static = static.rsplit('/', 1)[0] + '/'
            enroll(action.group(1) + static, required=True)
        if path.endswith(('.yml', '.yaml')):
            for reference in re.findall(r'uses:\s*[\'"]?(\./[\w./-]+)', text):
                enroll(local(reference), required=True, executable=True)
        for reference in _PATH.findall(text):
            resolve(reference, path)
        for reference in re.findall(r'(?<![\w.-])([\w./-]+\.(?:py|sh|bash|js|mjs|cjs|ts|tsx))\b', text):
            resolve(reference, path)
        # Path-building expressions (Path(__file__).parents[1] / '_shared'),
        # JS URL imports and dynamic loaders often split a path into literals.
        # Matching script/directory suffixes add whole trees, including every
        # ambiguous match. Metadata literals add only their exact file: they
        # are not evidence of executing every sibling at the repository root.
        for literal in _LITERAL.findall(text):
            literal = literal.removeprefix('./').rstrip('/')
            if not literal or literal == '.':
                continue
            for candidate in suffixes.get(literal, ()):
                if candidate in directories or candidate.endswith(('.py', '.sh', '.bash', '.js', '.mjs', '.cjs', '.ts', '.tsx')):
                    enroll(candidate)
                else:
                    selected.add(candidate)
        # An explicit run/script path is required even if absent from the tree.
        if path.endswith(('.yml', '.yaml', '.sh', '.bash')):
            for reference in re.findall(r'(?:^|[\s;|])(?:python[\d.]*|bash|sh|node|bun|source)\s+[\'"]?((?:[\w.-]+/)+[\w.-]+|[\w.-]+\.(?:py|sh|bash|js|mjs|cjs|ts|tsx))', text):
                resolve(reference, path, required=True)
            for reference in re.findall(r'(?:^|[\n;|]|run:)\s*[\'"]?((?:\./|\.\./)[\w./-]+)', text):
                resolve(reference, path, required=True)
        if not path.endswith('.py'):
            continue
        try:
            module = ast.parse(text, filename=path)
        except SyntaxError as error:
            raise DependencyUnknown('python-source-unparseable:' + path) from error
        for node in ast.walk(module):
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            names = ([alias.name for alias in node.names] if isinstance(node, ast.Import)
                     else [node.module or ''])
            for name in names:
                relative = isinstance(node, ast.ImportFrom) and node.level
                prefix = posixpath.dirname(path)
                if relative:
                    for _ in range(node.level - 1):
                        prefix = posixpath.dirname(prefix)
                bases = [prefix] if relative else [posixpath.dirname(path), '']
                found = False
                for base in bases:
                    reference = posixpath.join(base, name.replace('.', '/'))
                    resolved = enroll(reference + '.py')
                    resolved = enroll(reference) or resolved
                    if resolved and name:
                        enroll(posixpath.join(base, name.split('.')[0]))
                    found = resolved or found
                # A sys.path helper directory can live outside the script's
                # parent. Match all local module suffixes, not only sys.path[0].
                if not relative:
                    suffix = name.replace('.', '/')
                    for ending in (suffix + '.py', suffix):
                        for candidate in suffixes.get(ending, ()):
                            found = enroll(candidate) or found
                            enroll(candidate[:-len(ending)] + name.split('.')[0])
                if relative and not found:
                    raise DependencyUnknown('relative-import-missing:' + path + ':' + name)
    return sorted(selected)


def touches(pin, changed):
    """Positive relevance only: roots and conservatively resolved trees."""
    roots = [r for r in pin.get('roots', []) if r]
    declared = set(pin.get('dependency_paths', []))
    return any(path in declared or any(path == root or path.startswith(root.rstrip('/') + '/')
                                      for root in roots) for path in changed)
