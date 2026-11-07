"""SHA-only source-provenance proof, used before push and at exact PR head."""
from __future__ import annotations

from difflib import SequenceMatcher
import re
import yaml

SHA = re.compile(r'[a-fA-F0-9]{40}')


def prove_files(before: dict[str, str], after: dict[str, str], pins: list[dict], target: str,
                *, require_main: bool = True) -> list[str]:
    failures = []
    if set(before) != set(after):
        return ['file-set-changed']
    by_file = {}
    for pin in pins:
        by_file.setdefault(pin['path'], []).append(pin)
    changed = False
    for path, old in before.items():
        new = after[path]
        if old == new:
            continue
        changed = True
        allowed = by_file.get(path, [])
        # Independently require that every byte edit is one known SHA. Comments,
        # whitespace and line order remain byte-identical.
        edits = [op for op in SequenceMatcher(None, old, new, autojunk=False).get_opcodes() if op[0] != 'equal']
        # SequenceMatcher can split a SHA on coincident hex digits; compare the
        # entire candidate with the source-defined SHA spans instead.
        expected = old
        for pin in sorted(allowed, key=lambda p: p['start'], reverse=True):
            if old[pin['start']:pin['end']].lower() != pin['sha'].lower():
                failures.append(f'{path}:pin-span-mismatch')
                continue
            expected = expected[:pin['start']] + target + expected[pin['end']:]
            if require_main:
                line = old[pin['end']:].split('\n', 1)[0]
                if not re.match(r'''["']?\s+#\s+main\s*$''', line):
                    failures.append(f'{path}:missing-main-comment')
        if expected != new:
            failures.append(f'{path}:not-sha-only')
        try:
            # Match parsed YAML as well as the textual diff. An exact span
            # substitution is not enough if the parser interprets the value as
            # something other than a pinned uses/ref scalar.
            old_yaml, new_yaml = yaml.safe_load(old), yaml.safe_load(new)
            pairs = []
            def walk(a, b, keys=()):
                if isinstance(a, dict) and isinstance(b, dict) and a.keys() == b.keys():
                    for key in a:
                        walk(a[key], b[key], (*keys, key))
                elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
                    for i, (left, right) in enumerate(zip(a, b)):
                        walk(left, right, (*keys, i))
                elif a != b:
                    pairs.append((keys, a, b))
            walk(old_yaml, new_yaml)
            if not pairs or any(not k or k[-1] not in ('uses', 'ref') or not isinstance(a, str)
                                or not isinstance(b, str) for k, a, b in pairs):
                failures.append(f'{path}:parsed-yaml-diff')
        except yaml.YAMLError:
            failures.append(f'{path}:invalid-yaml')
        if not edits:
            failures.append(f'{path}:missing-line-diff')
    if not changed:
        failures.append('empty-diff')
    return sorted(set(failures))
